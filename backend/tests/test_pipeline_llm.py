"""LLM-mode pipeline tests.

The real AnthropicProvider / OpenAIProvider classes are used; only the HTTP layer is
replaced by httpx.MockTransport returning scripted provider responses. This tests the
provider adapters, schema validation, SQL repair loop, cross-checks and claim
verification without network access. (These are test doubles, not app behaviour.)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text

from app.config import Settings
from app.db import app_tx
from app.llm.base import LLMError
from app.llm.providers import AnthropicProvider, OpenAIProvider
from app.pipeline.orchestrator import run_analysis
from app.security.auth import dataset_for_user, load_user

pytestmark = pytest.mark.db
NOW = datetime(2026, 10, 24, 16, tzinfo=timezone.utc)

PLAN = {"intent": "compare", "metrics": ["conversions"], "time_range": {"preset": "last_week"},
        "comparison": "previous_period", "group_by": ["campaign"], "interpretation_notes": "test"}
GOOD_SQL = (
    "SELECT CASE WHEN m.date BETWEEN DATE '2026-10-12' AND DATE '2026-10-18' THEN 'current' ELSE 'comparison' END "
    "AS period, m.campaign_id, c.campaign_name, SUM(m.spend) AS spend, SUM(m.impressions) AS impressions, "
    "SUM(m.clicks) AS clicks, SUM(m.conversions) AS conversions, SUM(m.revenue) AS revenue "
    "FROM analytics.campaign_daily_metrics m JOIN analytics.campaigns c ON c.campaign_id = m.campaign_id "
    "WHERE m.date BETWEEN DATE '2026-10-05' AND DATE '2026-10-18' GROUP BY 1, 2, 3"
)
WRONG_RANGE_SQL = GOOD_SQL.replace("BETWEEN DATE '2026-10-05' AND DATE '2026-10-18'",
                                   "BETWEEN DATE '2026-10-07' AND DATE '2026-10-18'")
GOOD_EXPL = {
    "summary": "Conversions fell {{total.conversions.pct_change|abs}} to {{total.conversions.current}}; the largest "
               "contributor was Prospecting - Lookalike ({{seg.c003.conversions.contribution}}).",
    "observed_facts": [{"text": "Conversions: {{total.conversions.comparison}} → {{total.conversions.current}}."}],
    "contributions": [{"text": "Prospecting - Lookalike contributed {{seg.c003.conversions.contribution}}."}],
    "possible_explanations": [{"text": "A post-click change may explain this.", "confidence": "low"}],
    "recommended_actions": [{"text": "Review the campaign's change history.", "rationale": "Largest contributor."}],
    "limitations": ["Platform-attributed conversions may differ from backend orders."],
}
BAD_EXPL = {**GOOD_EXPL, "summary": "Conversions fell 12.7% because of a broken landing page."}


class Script:
    """Scripted Anthropic Messages API: responses keyed by the forced tool name."""

    def __init__(self, **queues):
        self.queues = {k: list(v) for k, v in queues.items()}
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        assert request.headers["x-api-key"] == "test-key"
        name = body["tool_choice"]["name"]
        payload = self.queues[name].pop(0) if len(self.queues[name]) > 1 else self.queues[name][0]
        if isinstance(payload, int):
            return httpx.Response(payload, json={"error": {"type": "overloaded"}})
        return httpx.Response(200, json={
            "model": "claude-test", "content": [{"type": "tool_use", "name": name, "input": payload, "id": "t1"}],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        })


def provider(script: Script) -> AnthropicProvider:
    s = Settings(llm_provider="anthropic", llm_api_key="test-key", llm_model="claude-test", llm_max_retries=1)
    return AnthropicProvider(s, client=httpx.Client(transport=httpx.MockTransport(script.handler)))


@pytest.fixture()
def ctx(seeded_db):
    with app_tx() as c:
        uid = c.execute(text("SELECT id FROM app.users WHERE is_demo")).scalar()
    u = load_user(uid)
    return u, dataset_for_user(u, None)


def _get(aid):
    with app_tx() as c:
        return dict(c.execute(text("SELECT * FROM app.analyses WHERE id = :i"), {"i": aid}).mappings().one())


def test_llm_happy_path(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[PLAN], SqlDraft=[{"sql": GOOD_SQL}], ExplanationDraft=[GOOD_EXPL])
    a = _get(run_analysis(user=u, dataset=ds, question="Why did conversions fall last week?", provider=provider(sc), now=NOW))
    assert a["status"] == "succeeded" and a["mode"] == "llm"
    assert a["explanation"]["source"] == "llm" and a["explanation"]["verification"]["passed"]
    assert "Prospecting - Lookalike (−462)" in a["explanation"]["summary"]["text"]
    assert a["result"]["checks"]["crosscheck"]["matched"] is True
    assert a["llm_usage"]["llm_calls"] == 3 and a["llm_usage"]["input_tokens"] == 3000
    # the interpretation prompt carried the schema but no secrets
    assert "test-key" not in json.dumps(sc.requests)


def test_unsafe_llm_sql_is_repaired_and_never_executed(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[PLAN], SqlDraft=[{"sql": "SELECT email, password_hash FROM app.users"}, {"sql": GOOD_SQL}],
                ExplanationDraft=[GOOD_EXPL])
    aid = run_analysis(user=u, dataset=ds, question="Why did conversions fall last week?", provider=provider(sc), now=NOW)
    a = _get(aid)
    assert a["status"] == "succeeded"
    attempts = a["pipeline_trace"]["sql_attempts"]
    assert attempts[0]["validation"]["ok"] is False and "schema 'app'" in attempts[0]["validation"]["reasons"][0]
    assert attempts[1]["validation"]["ok"] is True
    # the repair prompt told the model what was wrong
    assert "SQL validation failed" in sc.requests[2]["messages"][0]["content"]
    with app_tx() as c:
        rows = c.execute(text("SELECT executed FROM app.query_audit WHERE analysis_id = :a AND sql_text LIKE '%app.users%'"),
                         {"a": aid}).all()
    assert rows and all(r[0] is False for r in rows)


def test_persistently_unsafe_sql_fails_closed(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[PLAN], SqlDraft=[{"sql": "DELETE FROM analytics.campaigns"}])
    a = _get(run_analysis(user=u, dataset=ds, question="Why did conversions fall last week?", provider=provider(sc), now=NOW))
    assert a["status"] == "failed" and a["error_code"] == "sql_validation_failed"
    assert len(a["pipeline_trace"]["sql_attempts"]) == 3  # 1 + 2 repair attempts
    with app_tx() as c:
        assert c.execute(text("SELECT COUNT(*) FROM analytics.campaigns WHERE dataset_id = :d"), {"d": ds["id"]}).scalar() == 10


def test_crosscheck_catches_wrong_totals_and_triggers_repair(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[PLAN], SqlDraft=[{"sql": WRONG_RANGE_SQL}, {"sql": GOOD_SQL}], ExplanationDraft=[GOOD_EXPL])
    a = _get(run_analysis(user=u, dataset=ds, question="Why did conversions fall last week?", provider=provider(sc), now=NOW))
    assert a["status"] == "succeeded"
    first = a["pipeline_trace"]["sql_attempts"][0]
    assert first["result_validation"]["ok"] is False
    assert "independent deterministic query" in first["result_validation"]["problems"][0]


def test_unverifiable_llm_numbers_fall_back_to_deterministic_narrative(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[PLAN], SqlDraft=[{"sql": GOOD_SQL}], ExplanationDraft=[BAD_EXPL, BAD_EXPL])
    a = _get(run_analysis(user=u, dataset=ds, question="Why did conversions fall last week?", provider=provider(sc), now=NOW))
    assert a["status"] == "succeeded"
    e = a["explanation"]
    assert e["source"] == "deterministic_fallback"
    assert "12.7%" not in json.dumps(e["summary"])
    assert e["verification"]["rejected_llm_drafts"][0][0].startswith("number '12.7%'")


def test_invalid_plan_from_llm_is_retried_then_fails_cleanly(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[{"intent": "compare", "metrics": ["profit"]}])
    a = _get(run_analysis(user=u, dataset=ds, question="profit?", provider=provider(sc), now=NOW))
    assert a["status"] == "failed" and a["error_code"] == "interpretation_failed"
    assert len(sc.requests) == 2


def test_provider_errors_are_retried_then_reported(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[529, 529, 529])
    a = _get(run_analysis(user=u, dataset=ds, question="Why did conversions fall?", provider=provider(sc), now=NOW))
    assert a["status"] == "failed" and a["error_code"] == "llm_error"
    assert len(sc.requests) == 2  # llm_max_retries=1


def test_unsafe_question_is_rejected_by_llm_plan(ctx):
    u, ds = ctx
    sc = Script(QuestionPlan=[{"intent": "unsupported", "unsafe_request": True,
                               "unsupported_reason": "Read-only workspace."}])
    a = _get(run_analysis(user=u, dataset=ds, question="drop all tables", provider=provider(sc), now=NOW))
    assert a["status"] == "rejected" and a["error_code"] == "unsafe_request"


def test_openai_adapter_and_auth_error():
    def ok(req: httpx.Request):
        body = json.loads(req.content)
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": '{"sql": "SELECT 1"}'}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
    s = Settings(llm_provider="openai", llm_api_key="k", llm_model="m")
    r = OpenAIProvider(s, client=httpx.Client(transport=httpx.MockTransport(ok))).complete_json(
        system="s", user="u", schema={"type": "object"}, schema_name="SqlDraft")
    assert r.data == {"sql": "SELECT 1"} and r.input_tokens == 5
    bad = OpenAIProvider(s, client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(401))))
    with pytest.raises(LLMError) as e:
        bad.complete_json(system="s", user="u", schema={}, schema_name="x")
    assert e.value.code == "llm_auth_failed"
