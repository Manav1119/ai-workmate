"""DEMO MODE question interpreter (rule-based, no LLM).

Used only when no LLM provider is configured. It is deliberately simple and is always
labelled as rule-based in the API and UI; it never pretends an LLM was called.
"""

from __future__ import annotations

import re
from datetime import date

from app.analytics.metrics import METRICS
from app.pipeline.plan import Filter, QuestionPlan, Ranking, TimeSpec

PLATFORMS = {
    "google": "Google Ads", "google ads": "Google Ads", "adwords": "Google Ads",
    "meta": "Meta", "facebook": "Meta", "instagram": "Meta",
    "tiktok": "TikTok", "tik tok": "TikTok",
    "linkedin": "LinkedIn",
}
OBJECTIVES = {"awareness": "Awareness", "leads": "Leads", "lead gen": "Leads"}

UNSUPPORTED_TERMS = {
    "churn": "customer churn", "retention": "customer retention", "lifetime value": "customer lifetime value",
    "ltv": "customer lifetime value", "age": "audience age", "gender": "audience gender",
    "country": "geography", "region": "geography", "city": "geography", "device": "device",
    "keyword": "search keywords", "creative": "ad creatives", "landing page": "landing pages",
    "profit": "profit/margin", "margin": "profit/margin", "session": "website sessions",
    "bounce": "bounce rate", "email": "email marketing", "inventory": "inventory", "employee": "employees",
    "weather": "weather", "competitor": "competitors", "stock price": "stock prices", "nps": "NPS",
    "refund": "refunds", "return rate": "product returns", "hour": "hourly data",
}
UNSAFE = re.compile(
    r"\b(drop\s+(table|database|schema)|delete\s+(from|all|the|every)|truncate|insert\s+into|update\s+\w+\s+set|"
    r"alter\s+table|grant\s+|revoke\s+|create\s+(table|role|user)|pg_sleep|;\s*--|shutdown)\b",
    re.I,
)
METRIC_PATTERNS: list[tuple[str, str]] = [
    (r"\b(conversion rates?|conv\.? rates?|cvr)\b", "conversion_rate"),
    (r"\b(click[- ]through rates?|ctr)\b", "ctr"),
    (r"\b(cost per (acquisition|conversion|lead)|cpa|cac|cpl)\b", "cpa"),
    (r"\b(cost per click|cpc)\b", "cpc"),
    (r"\b(return on ad spend|roas)\b", "roas"),
    (r"\b(average order value|aov)\b", "aov"),
    (r"\b(conversions?|purchases?|orders?|leads?|sign-?ups?)\b", "conversions"),
    (r"\b(revenue|sales value|conversion value|income|gmv)\b", "revenue"),
    (r"\b(spend|spent|spending|cost|budget)\b", "spend"),
    (r"\b(clicks?|traffic)\b", "clicks"),
    (r"\b(impressions?|views)\b", "impressions"),
]
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
OVERVIEW = ["conversions", "spend", "revenue", "cpa", "roas"]


def _metrics(q: str) -> list[str]:
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for pat, key in METRIC_PATTERNS:
        for m in re.finditer(pat, q):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append((m.start(), key))
    out: list[str] = []
    for _, k in sorted(found):
        if k not in out:
            out.append(k)
    return out


def _time(q: str, anchor: date) -> tuple[TimeSpec | None, str]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|until|through|and|-|–)\s*(\d{4}-\d{2}-\d{2})", q)
    if m:
        return TimeSpec(preset="custom", start=date.fromisoformat(m.group(1)), end=date.fromisoformat(m.group(2))), "explicit dates"
    m = re.search(r"\b(?:last|past|previous)\s+(\d{1,3})\s+days?\b", q)
    if m:
        n = int(m.group(1))
        if f"last_{n}_days" in TimeSpec.model_fields["preset"].annotation.__args__:  # type: ignore[union-attr]
            return TimeSpec(preset=f"last_{n}_days"), f"last {n} days"
        from datetime import timedelta
        return TimeSpec(preset="custom", start=anchor - timedelta(days=n - 1), end=anchor), f"last {n} days"
    if re.search(r"\byesterday\b", q):
        return TimeSpec(preset="custom", start=anchor, end=anchor), "latest day with data"
    if re.search(r"\b(last|past|previous) week\b", q):
        return TimeSpec(preset="last_week"), "last complete week"
    if re.search(r"\bthis week\b", q):
        return TimeSpec(preset="this_week"), "this week"
    if re.search(r"\b(last|past|previous) month\b", q):
        return TimeSpec(preset="last_month"), "last month"
    if re.search(r"\b(this month|month to date|mtd)\b", q):
        return TimeSpec(preset="this_month"), "month to date"
    if re.search(r"\b(last|past) (quarter|3 months|three months)\b", q):
        return TimeSpec(preset="last_90_days"), "last 90 days"
    if re.search(r"\b(all time|overall|entire|whole period|all data)\b", q):
        return TimeSpec(preset="all_time"), "all data"
    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b", q):
            from calendar import monthrange
            year = anchor.year if num <= anchor.month else anchor.year - 1
            return TimeSpec(preset="custom", start=date(year, num, 1), end=date(year, num, monthrange(year, num)[1])), name
    return None, ""


def interpret(question: str, anchor: date, campaign_names: list[str]) -> QuestionPlan:
    raw = question.strip()
    q = raw.lower()
    notes: list[str] = ["Rule-based demo interpreter (no LLM call)."]

    if UNSAFE.search(raw):
        return QuestionPlan(
            intent="unsupported", unsafe_request=True,
            unsupported_reason="This workspace is read-only. Requests to modify, delete or administer data are not supported.",
            interpretation_notes="Detected a data-modification request.",
        )
    for term, label in UNSUPPORTED_TERMS.items():
        if re.search(rf"\b{re.escape(term)}s?\b", q):
            return QuestionPlan(
                intent="unsupported",
                unsupported_reason=(
                    f"The dataset has no {label} data. Available: daily spend, impressions, clicks, conversions and "
                    "revenue by campaign, platform and objective."
                ),
                interpretation_notes=f"Question refers to '{term}', which is not in the approved schema.",
            )

    metrics = _metrics(q)
    tspec, tnote = _time(q, anchor)
    if tnote:
        notes.append(f"Time range: {tnote}.")

    filters: list[Filter] = []
    plats = sorted({v for k, v in PLATFORMS.items() if re.search(rf"\b{re.escape(k)}\b", q)})
    if plats:
        filters.append(Filter(dimension="platform", values=plats))
    for k, v in OBJECTIVES.items():
        if re.search(rf"\b{k}\b objective|\bobjective\b.*\b{k}\b", q):
            filters.append(Filter(dimension="objective", values=[v]))
    named = [n for n in campaign_names if n.lower() in q]
    if named:
        filters.append(Filter(dimension="campaign_name", values=named[:5]))
    ids = sorted(set(re.findall(r"\b(c\d{3})\b", q)))
    if ids:
        filters.append(Filter(dimension="campaign_id", values=[i.upper() for i in ids]))

    group_by: list[str] = []
    if re.search(r"\b(by|per|each|which|what) (campaign|campaigns)\b|\bcampaigns?\b", q) and not named:
        group_by.append("campaign")
    if re.search(r"\b(by|per|each|which|across) (platform|channel)s?\b|\bplatforms\b|\bchannels\b", q):
        group_by = ["platform"]
    if re.search(r"\bby objective|per objective|objectives\b", q):
        group_by = ["objective"]

    ranking = None
    m = re.search(r"\b(top|best|highest|bottom|worst|lowest)\s*(\d{1,2})?\b", q)
    if m:
        word = m.group(1)
        hib = METRICS[metrics[0]].higher_is_better if metrics else True
        if word in ("best", "worst"):  # direction depends on the metric (worst CPA = highest CPA)
            order = "desc" if (word == "best") == hib else "asc"
        else:
            order = "asc" if word in ("bottom", "lowest") else "desc"
        ranking = Ranking(order=order, limit=int(m.group(2)) if m.group(2) else 5)

    if re.search(r"\b(anomal\w*|unusual|outliers?|spikes?|strange|abnormal|weird)\b", q):
        return QuestionPlan(
            intent="anomaly_scan", metrics=metrics or [], time_range=tspec or TimeSpec(preset="last_28_days"),
            filters=filters, interpretation_notes=" ".join(notes + ["Answered by the statistical anomaly engine."]),
        )

    is_trend = re.search(r"\b(trend|over time|daily|day by day|by day|per day|each day|weekly|by week|per week|timeline)\b", q)
    is_compare = re.search(
        r"\b(why|drop\w*|fall|fell|fallen|declin\w*|decreas\w*|increas\w*|ris\w*|grew|grow\w*|chang\w*|compare\w*|"
        r"comparison|vs\.?|versus|contribut\w*|drove|driv\w*|impact\w*|went (up|down)|jump\w*|spik\w*|worse|better than)\b",
        q,
    )
    is_highlight = re.search(r"\bhigh (spend|cost)\b.*\b(low|poor|weak)\b", q)

    if is_highlight:
        return QuestionPlan(
            intent="breakdown",
            metrics=list(dict.fromkeys(["spend", "conversion_rate", *metrics])),
            primary_metric="conversion_rate" if "conversion_rate" in metrics or not metrics else metrics[0],
            time_range=tspec or TimeSpec(preset="last_28_days"),
            group_by=group_by or ["campaign"], filters=filters, ranking=ranking, highlight="high_cost_low_efficiency",
            interpretation_notes=" ".join(notes + [
                "Flags segments with at least median spend and a below-overall efficiency metric."]),
        )
    if is_trend:
        gb = ["week" if re.search(r"\bweekly|by week|per week\b", q) else "date"]
        seg = [g for g in group_by if g in ("platform", "objective")]
        return QuestionPlan(
            intent="trend", metrics=metrics or ["conversions"], time_range=tspec or TimeSpec(preset="last_30_days"),
            group_by=gb + seg[:1], filters=filters, interpretation_notes=" ".join(notes),
        )
    if is_compare:
        if not metrics:
            metrics = list(OVERVIEW)
            notes.append("No metric named; comparing the core KPIs.")
        if re.search(r"\b(why|contribut\w*|drove|driv\w*|which|what caused|reason|explain)\b", q) and not group_by:
            group_by = ["campaign"]
        cmp_ = "same_period_last_year" if re.search(r"\b(last year|year over year|yoy)\b", q) else "previous_period"
        return QuestionPlan(
            intent="compare", metrics=metrics, time_range=tspec or TimeSpec(preset="last_week"), comparison=cmp_,
            group_by=group_by[:1], filters=filters, ranking=ranking, interpretation_notes=" ".join(notes),
        )
    if group_by or ranking:
        return QuestionPlan(
            intent="breakdown", metrics=metrics or ["spend", "conversions", "cpa"],
            time_range=tspec or TimeSpec(preset="last_28_days"), group_by=group_by or ["campaign"],
            filters=filters, ranking=ranking, interpretation_notes=" ".join(notes),
        )
    if metrics:
        return QuestionPlan(
            intent="aggregate", metrics=metrics, time_range=tspec or TimeSpec(preset="last_7_days"),
            filters=filters, interpretation_notes=" ".join(notes),
        )
    return QuestionPlan(
        intent="ambiguous",
        clarification_question="I couldn't tell which metric or comparison you mean. What would you like to look at?",
        clarification_options=[
            "Why did conversions fall last week?",
            "Compare this week with the previous week",
            "Show the daily ROAS trend for the last 30 days",
            "Which campaigns have high spend but low conversion rates?",
        ],
        interpretation_notes=" ".join(notes + ["No metric, comparison or grouping could be identified."]),
    )


def known_metric_labels() -> list[str]:
    return [m.label for m in METRICS.values()]
