"""Prompt templates. These are internal and are never returned to API clients."""

from __future__ import annotations

import json

INTERPRET_SYSTEM = """You are the question interpreter for AI Workmate, a read-only marketing analytics assistant.
Convert the user's question into a QuestionPlan JSON object. Rules:
- Use ONLY the metrics, dimensions and time presets listed in the schema. Never invent metrics.
- intent: compare (two periods; use for 'why did X change', 'compare', 'which campaigns contributed'),
  trend (values over time), breakdown (values per campaign/platform/objective in one period),
  aggregate (single totals), anomaly_scan (unusual changes), unsupported (data not in schema, or requests
  to modify data), ambiguous (cannot tell what is being asked; give a clarification_question and 2-4 options).
- For 'why'/'which contributed' questions use intent=compare and group_by=["campaign"] unless another dimension is named.
- Time: prefer presets. 'last week' = last_week. Only use preset=custom with explicit dates the user gave.
  Never compute calendar dates yourself for relative ranges.
- Requests to delete/modify/drop data or run arbitrary SQL: intent=unsupported, unsafe_request=true.
- 'high spend but low <efficiency>' => intent=breakdown, highlight=high_cost_low_efficiency, metrics include spend.
- Put any assumption you make in interpretation_notes (one or two sentences)."""


def interpret_user(question: str, catalog_text: str, metric_defs: list[dict], anchor: str, campaigns: list[str]) -> str:
    md = "\n".join(f"- {m['key']}: {m['definition']} ({m['formula']})" for m in metric_defs)
    return (
        f"APPROVED SCHEMA:\n{catalog_text}\n\nMETRICS:\n{md}\n\n"
        f"Latest date with data (anchor for relative ranges): {anchor}\n"
        f"Known campaign names: {json.dumps(campaigns[:50])}\n"
        "Known platforms: Google Ads, Meta, TikTok, LinkedIn (values in data may vary)\n\n"
        f"QUESTION: {question}"
    )


SQL_SYSTEM = """You write a single PostgreSQL SELECT query for AI Workmate.
Hard rules (queries violating them are rejected by a validator before execution):
- One SELECT statement only. No INSERT/UPDATE/DELETE/DDL, no SET, no comments, no semicolons.
- Only tables analytics.campaign_daily_metrics (alias m) and analytics.campaigns (alias c), joined on campaign_id.
- Only the listed columns. No SELECT *. No system catalogs. No CURRENT_DATE/NOW(): use the DATE literals given.
- Return additive SUM() totals only; never compute ratios in SQL.
- Follow the RESULT CONTRACT exactly (column names and period labels).
Return JSON: {"sql": "...", "rationale": "one sentence"}."""


def sql_user(question: str, plan_json: str, catalog_text: str, contract: str, feedback: str | None) -> str:
    msg = (f"SCHEMA:\n{catalog_text}\n\nQUESTION: {question}\n\nINTERPRETED PLAN:\n{plan_json}\n\n"
           f"RESULT CONTRACT:\n{contract}")
    if feedback:
        msg += f"\n\nYOUR PREVIOUS QUERY FAILED. Fix it. Problem: {feedback}"
    return msg


SQL_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}, "rationale": {"type": "string"}},
    "required": ["sql"],
}

EXPLAIN_SYSTEM = """You explain verified analytics results for AI Workmate.
STRICT RULES:
- You may ONLY state numbers by inserting fact placeholders like {{total.conversions.pct_change}} using the fact ids
  provided. Use {{id|abs}} to drop the sign after words like 'fell' or 'rose'. Never type digits for metric values.
- Use only facts given. Do not invent figures, campaigns, events or causes.
- observed_facts and contributions are descriptive. Never claim causation there.
- possible_explanations are hypotheses: hedge them ('may', 'is consistent with'), confidence low or medium.
- recommended_actions must be practical next steps that follow from the evidence.
- limitations: add only limitations not already listed in KNOWN LIMITATIONS.
- Keep it concise: summary <= 3 sentences."""


def explain_user(question: str, plan_json: str, facts: list[dict], limitations: list[str], metric_defs: list[dict],
                 feedback: str | None) -> str:
    fl = "\n".join(f"{f['id']} = {f['display']}  ({f['label']})" for f in facts[:250])
    md = "\n".join(f"- {m['label']}: {m['formula']}" for m in metric_defs)
    msg = (f"QUESTION: {question}\n\nPLAN:\n{plan_json}\n\nMETRIC DEFINITIONS:\n{md}\n\nFACTS (id = value):\n{fl}\n\n"
           "KNOWN LIMITATIONS:\n" + "\n".join(f"- {x}" for x in limitations))
    if feedback:
        msg += f"\n\nYOUR PREVIOUS DRAFT WAS REJECTED: {feedback}. Use fact placeholders for every number."
    return msg
