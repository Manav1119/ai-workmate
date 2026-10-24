import io

import pytest

pytestmark = pytest.mark.db

GOOD = """date,campaign,channel,cost,impr,clicks,purchases,conversion_value
2026-09-01,Spring Sale,Meta,100.50,10000,200,10,800
2026-09-01,Brand,Google Ads,50,4000,300,20,1500
2026-09-02,Spring Sale,Meta,110,11000,210,9,700
2026-09-02,Brand,Google Ads,55,4200,320,22,1600
"""


def _upload(client, headers, content: bytes, name="data.csv"):
    return client.post("/api/data-sources/upload", files={"file": (name, io.BytesIO(content), "text/csv")}, headers=headers)


def test_upload_preview_mapping_and_import(client, make_user):
    u = make_user()
    r = _upload(client, u, GOOD.encode())
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["rows"] == 4
    m = p["suggested_mapping"]
    assert m["date"] == "date" and m["campaign_name"] == "campaign" and m["spend"] == "cost"
    assert m["conversions"] == "purchases" and m["revenue"] == "conversion_value" and m["platform"] == "channel"
    imp = client.post(f"/api/data-sources/imports/{p['upload_id']}",
                      json={"mapping": m, "dataset_name": "My test data", "reporting_timezone": "UTC"}, headers=u)
    assert imp.status_code == 201, imp.text
    s = imp.json()
    assert s["rows_imported"] == 4 and s["campaigns"] == 2 and s["duplicate_rows"] == 0
    ds = s["dataset_id"]
    # the dataset is usable for analysis, and isolated
    a = client.post("/api/analyses", json={"question": "Total spend all time", "dataset_id": ds}, headers=u).json()
    assert a["status"] == "succeeded"
    spend = next(k for k in a["result"]["calculations"]["key_metrics"] if k["metric"] == "spend")
    assert spend["current"] == pytest.approx(315.5)
    other = make_user()
    assert client.post("/api/analyses", json={"question": "Total spend", "dataset_id": ds}, headers=other).status_code == 404
    assert client.get(f"/api/data-sources/{ds}/preview", headers=other).status_code == 404
    assert all(d["id"] != ds for d in client.get("/api/data-sources", headers=other).json()["items"])
    assert client.delete(f"/api/data-sources/{ds}", headers=other).status_code == 404
    assert client.delete(f"/api/data-sources/{ds}", headers=u).status_code == 204


def test_duplicates_types_and_missing_mapping_are_reported(client, make_user):
    u = make_user()
    dup = GOOD + "2026-09-02,Brand,Google Ads,55,4200,320,22,1600\n"
    p = _upload(client, u, dup.encode()).json()
    r = client.post(f"/api/data-sources/imports/{p['upload_id']}",
                    json={"mapping": p["suggested_mapping"], "dataset_name": "dup"}, headers=u)
    assert r.status_code == 422 and any("duplicate" in d for d in r.json()["error"]["details"])
    bad = GOOD.replace("100.50", "abc").replace("4200", "-5")
    p = _upload(client, u, bad.encode()).json()
    r = client.post(f"/api/data-sources/imports/{p['upload_id']}",
                    json={"mapping": p["suggested_mapping"], "dataset_name": "bad"}, headers=u)
    details = " ".join(r.json()["error"]["details"])
    assert r.status_code == 422 and "non-numeric" in details and "negative" in details
    m = dict(p["suggested_mapping"], revenue=None)
    r = client.post(f"/api/data-sources/imports/{p['upload_id']}", json={"mapping": m, "dataset_name": "x"}, headers=u)
    assert r.status_code == 422 and "revenue" in " ".join(r.json()["error"]["details"])
    clicks = GOOD.replace("10000,200", "10,200")
    p = _upload(client, u, clicks.encode()).json()
    r = client.post(f"/api/data-sources/imports/{p['upload_id']}",
                    json={"mapping": p["suggested_mapping"], "dataset_name": "x"}, headers=u)
    assert "more clicks than impressions" in " ".join(r.json()["error"]["details"])


def test_formula_injection_is_neutralised_and_timestamps_converted(client, make_user):
    u = make_user()
    csv = ("timestamp,campaign_name,platform,spend,impressions,clicks,conversions,revenue\n"
           "2026-09-01T20:00:00Z,=HYPERLINK(\"http://evil\"),Meta,10,1000,10,1,50\n"
           "2026-09-01T10:00:00Z,Normal,Meta,10,1000,10,1,50\n")
    p = _upload(client, u, csv.encode()).json()
    assert p["suggested_mapping"]["date"] == "timestamp"
    r = client.post(f"/api/data-sources/imports/{p['upload_id']}",
                    json={"mapping": p["suggested_mapping"], "dataset_name": "tz", "reporting_timezone": "Asia/Kolkata"},
                    headers=u)
    assert r.status_code == 201, r.text
    s = r.json()
    # 20:00 UTC on Sep 1 is Sep 2 in India; 10:00 UTC stays Sep 1
    assert s["date_range"] == ["2026-09-01", "2026-09-02"]
    assert any("formula injection" in w for w in s["warnings"])
    prev = client.get(f"/api/data-sources/{s['dataset_id']}/preview", headers=u).json()
    names = {c["campaign_name"] for c in prev["campaigns"]}
    assert "'=HYPERLINK(\"http://evil\")" in names


@pytest.mark.parametrize("content,name,code", [
    (b"\x00\x01\x02binary", "x.csv", 415),
    (b"", "x.csv", 422),
    (GOOD.encode(), "x.xlsx", 415),
    ("date,spend\n".encode(), "x.csv", 422),
    ("caf\xe9".encode("latin-1"), "x.csv", 415),
])
def test_rejected_files(client, make_user, content, name, code):
    u = make_user()
    assert _upload(client, u, content, name).status_code == code


def test_row_limit(client, make_user, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_max_rows", 3)
    u = make_user()
    r = _upload(client, u, GOOD.encode())
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_many_rows"


def test_demo_account_cannot_store_uploads(client, demo):
    p = _upload(client, demo, GOOD.encode()).json()
    r = client.post(f"/api/data-sources/imports/{p['upload_id']}",
                    json={"mapping": p["suggested_mapping"], "dataset_name": "x"}, headers=demo)
    assert r.status_code == 403
