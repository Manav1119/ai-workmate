import pytest
from pydantic import ValidationError

from app.pipeline.explain import ExplanationDraft, finalize, verify_text
from app.pipeline.plan import QuestionPlan

FACTS = [
    {"id": "total.conversions.current", "label": "Conversions current", "value": 4763.0, "display": "4,763"},
    {"id": "total.conversions.comparison", "label": "Conversions comparison", "value": 4914.0, "display": "4,914"},
    {"id": "total.conversions.pct_change", "label": "% change", "value": -3.0728, "display": "−3.1%"},
    {"id": "total.conversion_rate.current", "label": "CVR", "value": 0.0353, "display": "3.53%"},
    {"id": "total.spend.current", "label": "Spend", "value": 118428.4, "display": "$118,428.40"},
]
F = {f["id"]: f for f in FACTS}


def test_placeholders_render_and_are_traceable():
    d = ExplanationDraft(summary="Conversions fell {{total.conversions.pct_change|abs}} to {{total.conversions.current}}.")
    out, violations = finalize(d, FACTS, "Why did conversions fall?", "llm")
    assert not violations
    assert out["summary"]["text"] == "Conversions fell 3.1% to 4,763."
    facts = [p for p in out["summary"]["parts"] if p["type"] == "fact"]
    assert [p["fact_id"] for p in facts] == ["total.conversions.pct_change", "total.conversions.current"]
    assert out["verification"]["passed"]


@pytest.mark.parametrize("text", [
    "Conversions fell 12.5% last week.",
    "Spend was $99,999.",
    "ROAS is 4.2x.",
    "Conversions dropped by 1,234.",
])
def test_invented_numbers_are_rejected(text):
    v, n = verify_text(text, F, set())
    assert v and n == 1


@pytest.mark.parametrize("text", [
    "Conversions were 4,763 vs 4,914.",          # literal numbers that match facts
    "Conversion rate was 3.53%.",                # percent unit facts (value * 100)
    "Spend reached $118,428.40.",
    "3 campaigns moved on 2026-10-12 and Oct 12, 2026.",  # small counts and dates are not metric claims
])
def test_numbers_matching_facts_or_benign_are_accepted(text):
    v, _ = verify_text(text, F, set())
    assert v == []


def test_numbers_from_question_are_allowed_and_unknown_ids_flagged():
    d = ExplanationDraft(summary="Over the last 45 days spend was {{total.spend.current}}; {{made.up.fact}}.")
    out, violations = finalize(d, FACTS, "spend over the last 45 days", "llm")
    assert violations == ["unknown fact id 'made.up.fact'"]


def test_causal_language_outside_hypotheses_is_warned():
    d = ExplanationDraft(summary="Conversions fell because of the new landing page.",
                         possible_explanations=[{"text": "This may be caused by a landing page change.", "confidence": "low"}])
    out, _ = finalize(d, FACTS, "q", "llm")
    assert len(out["verification"]["warnings"]) == 1


def test_llm_response_schema_validation():
    with pytest.raises(ValidationError):
        ExplanationDraft.model_validate({"observed_facts": []})  # summary missing
    with pytest.raises(ValidationError):
        ExplanationDraft.model_validate({"summary": "x", "possible_explanations": [{"text": "y", "confidence": "certain"}]})
    with pytest.raises(ValidationError):
        QuestionPlan.model_validate({"intent": "compare", "metrics": ["profit"]})
    with pytest.raises(ValidationError):
        QuestionPlan.model_validate({"intent": "compare", "metrics": []})
    with pytest.raises(ValidationError):
        QuestionPlan.model_validate({"intent": "trend", "metrics": ["spend"], "time_range": {"preset": "custom"}})
    p = QuestionPlan.model_validate({"intent": "compare", "metrics": ["cpa"]})
    assert p.comparison == "previous_period" and p.primary_metric == "cpa"
    t = QuestionPlan.model_validate({"intent": "trend", "metrics": ["roas"]})
    assert t.group_by == ["date"]
