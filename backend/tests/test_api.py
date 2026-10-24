"""REST API tests: auth, isolation, investigations, anomalies, reports, errors."""

import pytest

pytestmark = pytest.mark.db

Q = "Why did conversions fall last week?"


def test_health_and_definitions(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["llm_mode"] == "demo"
    defs = client.get("/api/metric-definitions").json()["metrics"]
    assert {d["key"] for d in defs} >= {"cpa", "roas", "conversion_rate"}


def test_auth_required_and_error_format(client):
    r = client.get("/api/analyses")
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "unauthenticated" and err["request_id"]
    assert r.headers["x-request-id"] == err["request_id"]
    assert client.get("/api/analyses", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_cookie_session_requires_csrf_header_for_writes(client):
    client.post("/api/auth/demo")  # sets httpOnly cookie
    assert client.get("/api/auth/me").status_code == 200
    r = client.post("/api/analyses", json={"question": Q})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_check_failed"
    r = client.post("/api/analyses", json={"question": Q}, headers={"X-Requested-With": "aiworkmate"})
    assert r.status_code == 201
    client.post("/api/auth/logout")


def test_register_login_and_duplicate(client):
    r = client.post("/api/auth/register", json={"email": "pm@example.com", "password": "a-long-password", "display_name": "PM"})
    assert r.status_code in (201, 409)
    r = client.post("/api/auth/register", json={"email": "pm@example.com", "password": "a-long-password", "display_name": "PM"})
    assert r.status_code == 409
    assert client.post("/api/auth/login", json={"email": "pm@example.com", "password": "wrong-password"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": "PM@example.com", "password": "a-long-password"})
    assert ok.status_code == 200 and ok.json()["user"]["display_name"] == "PM"
    weak = client.post("/api/auth/register", json={"email": "x@example.com", "password": "short", "display_name": "x"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "invalid_request"


def test_investigation_lifecycle(client, demo):
    r = client.post("/api/analyses", json={"question": Q}, headers=demo)
    assert r.status_code == 201
    a = r.json()
    assert a["status"] == "succeeded" and a["mode"] == "demo" and a["result_is_historical"] is False
    assert a["sql_validation"]["ok"] and "SELECT" in a["generated_sql"]
    calc = a["result"]["calculations"]
    km = {k["metric"]: k for k in calc["key_metrics"]}
    assert km["conversions"]["current"] == 4763 and km["conversions"]["comparison"] == 4914
    # chart and explanation agree with the query results
    chart = calc["charts"][0]
    contrib = {d["label"]: d["contribution"] for d in chart["data"]}
    assert contrib["Prospecting - Lookalike"] == -462
    assert "4,914 to 4,763" in a["explanation"]["summary"]["text"]
    rows = a["result"]["rows"]
    assert sum(r["conversions"] for r in rows if r["period"] == "current") == 4763
    # save, list/search, reopen (historical), export
    aid = a["id"]
    assert client.patch(f"/api/analyses/{aid}", json={"saved": True, "title": "Conversion dip"}, headers=demo).json()["saved"]
    lst = client.get("/api/analyses", params={"q": "conversions fall", "saved": True}, headers=demo).json()
    assert any(x["id"] == aid for x in lst["items"]) and lst["total"] >= 1
    again = client.get(f"/api/analyses/{aid}", headers=demo).json()
    assert again["result_is_historical"] is True and again["title"] == "Conversion dip"
    md = client.get(f"/api/analyses/{aid}/export", params={"format": "markdown"}, headers=demo)
    assert md.status_code == 200 and "## Summary" in md.text and "SYNTHETIC" in md.text
    pdf = client.get(f"/api/analyses/{aid}/export", params={"format": "pdf"}, headers=demo)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    retry = client.post(f"/api/analyses/{aid}/retry", headers=demo).json()
    assert retry["parent_id"] == aid and retry["id"] != aid and retry["result_is_historical"] is False


@pytest.mark.parametrize("question,status,code", [
    ("What is our customer churn rate?", "unsupported", "unsupported_question"),
    ("Please DROP TABLE campaigns", "rejected", "unsafe_request"),
    ("hmm what?", "needs_clarification", "ambiguous_question"),
    ("Total spend from 2019-01-01 to 2019-01-31", "needs_clarification", "no_data_in_range"),
])
def test_non_answerable_questions(client, demo, question, status, code):
    a = client.post("/api/analyses", json={"question": question}, headers=demo).json()
    assert a["status"] == status and a["error_code"] == code and a["error_message"]


def test_user_isolation(client, make_user, demo):
    alice, bob = make_user("Alice"), make_user("Bob")
    a = client.post("/api/analyses", json={"question": Q}, headers=alice).json()
    assert client.get(f"/api/analyses/{a['id']}", headers=bob).status_code == 404
    assert client.patch(f"/api/analyses/{a['id']}", json={"saved": True}, headers=bob).status_code == 404
    assert client.get(f"/api/analyses/{a['id']}/export", headers=bob).status_code == 404
    assert all(x["id"] != a["id"] for x in client.get("/api/analyses", headers=bob).json()["items"])
    rep = client.post("/api/reports", json={"analysis_id": a["id"]}, headers=alice).json()
    assert client.get(f"/api/reports/{rep['id']}", headers=bob).status_code == 404
    assert client.post("/api/reports", json={"analysis_id": a["id"]}, headers=bob).status_code == 404


def test_anomaly_listing_filters_and_per_user_states(client, make_user):
    u1, u2 = make_user("U1"), make_user("U2")
    data = client.get("/api/anomalies", headers=u1).json()
    assert data["total"] > 0 and data["sensitivity"] == "balanced"
    item = next(x for x in data["items"] if x["kind"] == "tracking_gap")
    assert item["campaign_name"] == "Shopping - Catalog" and item["data_quality_status"] == "suspected_tracking_issue"
    high = client.get("/api/anomalies", params={"severity": "high", "platform": "Meta"}, headers=u1).json()
    assert all(x["severity"] == "high" and x["platform"] == "Meta" for x in high["items"])
    dated = client.get("/api/anomalies", params={"date_from": "2026-10-10", "metric": "cpa"}, headers=u1).json()
    assert all(x["metric"] == "cpa" and x["episode_end"] >= "2026-10-10" for x in dated["items"])
    aid = item["id"]
    r = client.patch(f"/api/anomalies/{aid}", json={"status": "investigating", "note": "checking tag"}, headers=u1)
    assert r.status_code == 200 and r.json()["status"] == "investigating" and r.json()["previous_status"] == "new"
    assert client.patch(f"/api/anomalies/{aid}", json={"status": "resolved"}, headers=u1).json()["status"] == "resolved"
    # persisted, and invisible to another user
    mine = client.get("/api/anomalies", params={"status": "resolved"}, headers=u1).json()["items"]
    assert any(x["id"] == aid and x["note"] == "checking tag" for x in mine)
    theirs = [x for x in client.get("/api/anomalies", headers=u2).json()["items"] if x["id"] == aid][0]
    assert theirs["status"] == "new"
    assert client.patch(f"/api/anomalies/{aid}", json={"status": "bogus"}, headers=u1).status_code == 422
    assert client.patch("/api/anomalies/99999999", json={"status": "resolved"}, headers=u1).status_code == 404


def test_anomaly_sensitivity_setting_changes_visible_set(client, make_user):
    u = make_user()
    n_bal = client.get("/api/anomalies", headers=u).json()["total"]
    client.patch("/api/auth/me", json={"anomaly_sensitivity": "conservative"}, headers=u)
    n_con = client.get("/api/anomalies", headers=u).json()["total"]
    client.patch("/api/auth/me", json={"anomaly_sensitivity": "sensitive"}, headers=u)
    n_sen = client.get("/api/anomalies", headers=u).json()["total"]
    assert n_con < n_bal < n_sen
    assert client.patch("/api/auth/me", json={"reporting_timezone": "Mars/Olympus"}, headers=u).status_code == 422


def test_reports_and_briefing(client, demo):
    a = client.post("/api/analyses", json={"question": "Show the daily ROAS trend for the last 30 days"}, headers=demo).json()
    assert a["status"] == "succeeded" and a["result"]["calculations"]["charts"][0]["type"] == "line"
    rep = client.post("/api/reports", json={"analysis_id": a["id"], "title": "ROAS trend"}, headers=demo)
    assert rep.status_code == 201 and rep.json()["title"] == "ROAS trend"
    rid = rep.json()["id"]
    assert client.get(f"/api/reports/{rid}/export", params={"format": "pdf"}, headers=demo).content[:4] == b"%PDF"
    b = client.post("/api/briefings", headers=demo).json()
    assert b["generated_by"] == "deterministic" and "## New anomalies" in b["markdown"]
    assert {c["metric"] for c in b["changes"]} >= {"conversions", "cpa", "roas"}
    saved = client.post("/api/reports", json={"kind": "briefing"}, headers=demo)
    assert saved.status_code == 201 and saved.json()["kind"] == "briefing"
    assert client.get("/api/reports", params={"kind": "briefing"}, headers=demo).json()["total"] >= 1
    assert client.delete(f"/api/reports/{rid}", headers=demo).status_code == 204
    assert client.get(f"/api/reports/{rid}", headers=demo).status_code == 404


def test_overview_is_database_backed(client, demo):
    o = client.get("/api/metrics/overview", headers=demo).json()
    k = {x["metric"]: x for x in o["kpis"]}
    assert k["conversions"]["current"] == 4763 and k["spend"]["current"] == pytest.approx(118428.40)
    assert o["freshness"]["last_data_date"] == "2026-10-18" and o["dataset"]["is_synthetic"]
    assert len(o["series"]) == 60 and o["anomalies"]


def test_validation_limits_and_rate_limiting(client, make_user, monkeypatch):
    u = make_user()
    assert client.post("/api/analyses", json={"question": "x" * 501}, headers=u).status_code == 422
    assert client.post("/api/analyses", json={}, headers=u).status_code == 422
    big = client.post("/api/analyses", content=b"{" + b" " * 70000 + b"}",
                      headers={**u, "content-type": "application/json"})
    assert big.status_code == 413
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "analysis_rate_limit_per_minute", 2)
    codes = [client.post("/api/analyses", json={"question": "Total spend last week"}, headers=u).status_code
             for _ in range(3)]
    assert codes == [201, 201, 429]
    assert client.get("/api/nope", headers=u).json()["error"]["code"] == "not_found"


def test_schema_endpoint_hides_internal_columns(client, demo):
    s = client.get("/api/schema", headers=demo).json()
    cols = {c["name"] for t in s["tables"] for c in t["columns"]}
    assert "dataset_id" not in cols and {"spend", "campaign_name"} <= cols
