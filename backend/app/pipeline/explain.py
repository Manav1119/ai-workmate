"""Steps 8-9: explanation drafting, schema validation and numeric-claim verification.

Explanations reference numbers ONLY through fact placeholders: ``{{fact_id}}`` or
``{{fact_id|abs}}``. The application substitutes the formatted, deterministically computed
value. Any other number in the text is a *numeric claim* that must match a fact value
(within rounding tolerance), otherwise the draft is rejected (one LLM retry, then a
deterministic fallback narrative is used). This makes every displayed number traceable.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.analytics.metrics import METRICS

PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_.]+)(\|abs)?\s*\}\}")
NUMBER = re.compile(r"(?<![\w.])[-+−]?\$?\d[\d,]*(?:\.\d+)?\s?(?:%|x|pp)?(?![\w])")
DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}(?:, \d{4})?\b")
CAUSAL = re.compile(r"\b(caused by|because of|was due to|is due to|the reason (is|was)|resulted from|proves?)\b", re.I)


class Statement(BaseModel):
    text: str = Field(min_length=1, max_length=700)
    fact_ids: list[str] = Field(default_factory=list, max_length=12)


class PossibleExplanation(Statement):
    confidence: Literal["low", "medium"] = "low"


class Action(Statement):
    rationale: str | None = Field(default=None, max_length=400)


class ExplanationDraft(BaseModel):
    summary: str = Field(min_length=1, max_length=900)
    observed_facts: list[Statement] = Field(default_factory=list, max_length=8)
    contributions: list[Statement] = Field(default_factory=list, max_length=6)
    possible_explanations: list[PossibleExplanation] = Field(default_factory=list, max_length=5)
    recommended_actions: list[Action] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=8)


def _parse_number(tok: str) -> float | None:
    t = tok.replace("−", "-").replace("$", "").replace(",", "").replace("%", "").replace("pp", "").replace("x", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _candidates(fact: dict) -> list[float]:
    v = fact.get("value")
    if v is None:
        return []
    vals = [v, abs(v)]
    fid = fact["id"]
    metric = fid.split(".")[-2] if fid.count(".") >= 2 else ""
    if metric in METRICS and METRICS[metric].unit == "percent" and not fid.endswith(("pct_change", "share_of_change")):
        vals += [v * 100, abs(v) * 100]
    disp = _parse_number(re.sub(r"[^\d.,\-−]", "", fact.get("display", "")) or "x")
    if disp is not None:
        vals += [disp, abs(disp)]
    return vals


def _matches(num: float, facts: dict[str, dict]) -> bool:
    for f in facts.values():
        for c in _candidates(f):
            tol = max(abs(c) * 0.01, 0.051 if abs(c) < 100 else 0.5)
            if abs(abs(num) - abs(c)) <= tol:
                return True
    return False


def render_text(text: str, facts: dict[str, dict]) -> tuple[list[dict], list[str], list[str]]:
    """Return (parts, fact_ids_used, unknown_ids)."""
    parts: list[dict] = []
    used: list[str] = []
    unknown: list[str] = []
    pos = 0
    for m in PLACEHOLDER.finditer(text):
        if m.start() > pos:
            parts.append({"type": "text", "value": text[pos:m.start()]})
        fid, mod = m.group(1), m.group(2)
        f = facts.get(fid)
        if f is None:
            unknown.append(fid)
            parts.append({"type": "text", "value": "[unavailable]"})
        else:
            disp = f["display"]
            if mod and disp and disp[0] in "+−-±":
                disp = disp[1:]
            parts.append({"type": "fact", "value": disp, "fact_id": fid, "label": f["label"]})
            used.append(fid)
        pos = m.end()
    if pos < len(text):
        parts.append({"type": "text", "value": text[pos:]})
    return parts, used, unknown


def verify_text(text: str, facts: dict[str, dict], allowed_numbers: set[float]) -> tuple[list[str], int]:
    """Return (violations, numeric tokens checked) for literal numbers outside placeholders."""
    stripped = PLACEHOLDER.sub(" ", text)
    stripped = DATE_LIKE.sub(" ", stripped)
    violations: list[str] = []
    checked = 0
    for m in NUMBER.finditer(stripped):
        tok = m.group(0).strip()
        num = _parse_number(tok)
        if num is None:
            continue
        has_unit = any(u in tok for u in ("%", "$", "x", "pp"))
        if not has_unit and float(num).is_integer() and (0 <= num <= 10 or 1900 <= num <= 2100):
            continue  # small counts ("3 campaigns") and years
        checked += 1
        if num in allowed_numbers or _matches(num, facts):
            continue
        violations.append(f"number '{tok}' is not traceable to a computed fact")
    return violations, checked


def finalize(draft: ExplanationDraft, facts_list: list[dict], question: str, source: str,
             context_text: str = "") -> tuple[dict, list[str]]:
    """context_text: trusted text whose numbers may be repeated (question, period labels)."""
    facts = {f["id"]: f for f in facts_list}
    allowed = {n for n in (_parse_number(t) for t in NUMBER.findall(question + " " + context_text)) if n is not None}
    violations: list[str] = []
    warnings: list[str] = []
    checked_total = 0
    placeholders = 0

    def stmt(text: str, extra_ids: list[str] | None = None, *, causal_ok: bool = False) -> dict:
        nonlocal checked_total, placeholders
        parts, used, unknown = render_text(text, facts)
        placeholders += len(used)
        for u in unknown:
            violations.append(f"unknown fact id '{u}'")
        v, n = verify_text(text, facts, allowed)
        checked_total += n
        violations.extend(v)
        if not causal_ok and CAUSAL.search(text):
            warnings.append(f"causal wording outside 'possible explanations': '{CAUSAL.search(text).group(0)}'")
        ids = list(dict.fromkeys(used + [i for i in (extra_ids or []) if i in facts]))
        return {"text": "".join(p["value"] for p in parts), "parts": parts, "fact_ids": ids}

    out = {
        "source": source,
        "summary": stmt(draft.summary),
        "observed_facts": [stmt(s.text, s.fact_ids) for s in draft.observed_facts],
        "contributions": [stmt(s.text, s.fact_ids) for s in draft.contributions],
        "possible_explanations": [
            {**stmt(s.text, s.fact_ids, causal_ok=True), "confidence": s.confidence} for s in draft.possible_explanations
        ],
        "recommended_actions": [
            {**stmt(s.text, s.fact_ids, causal_ok=True), "rationale": s.rationale} for s in draft.recommended_actions
        ],
        "limitations": [stmt(t, causal_ok=True)["text"] for t in draft.limitations],
    }
    out["verification"] = {
        "numeric_tokens_checked": checked_total,
        "fact_placeholders_rendered": placeholders,
        "violations": violations,
        "warnings": warnings,
        "passed": not violations,
    }
    return out, violations
