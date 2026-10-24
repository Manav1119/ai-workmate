# PRD: AI Workmate v1

**Status:** v1 built (portfolio project). **Owner:** product + engineering (single builder).
Everything labelled *assumption* below is a hypothesis that has not been validated with users. No user interviews, usage data or business outcomes exist for this product yet.

## 1. Problem

People who own marketing or product numbers spend a large share of their week answering "what changed and why?": writing SQL, rebuilding the same comparisons, and explaining movements to stakeholders. General-purpose AI chat tools can draft SQL and prose quickly, but they:

- invent or miscompute numbers (e.g. averaging daily CPAs instead of dividing totals),
- can emit unsafe or wrong SQL with no guard rails,
- present correlation as causation and hide what they could not check.

The result is either slow manual analysis or fast answers nobody should trust.

## 2. Who it is for

Individual analysts, PMs/APMs, marketers and founders who have campaign-level performance data and need defensible answers, not dashboards. See [USER_PERSONAS.md](USER_PERSONAS.md) (assumption-based).

## 3. Jobs to be done

1. *When a KPI moves unexpectedly*, I want to find where the change came from, so I can decide whether to act before my next review.
2. *When I'm asked a data question in a meeting*, I want a correct answer with the query behind it, so I can defend it.
3. *When I start my day*, I want to know what is unusual and whether the data is fresh, so I don't miss problems or chase data glitches.
4. *When I share findings*, I want a clean report that separates facts from hypotheses, so stakeholders don't over-read it.

## 4. Solution summary

A workspace where a question becomes an auditable investigation: interpretation → validated read-only SQL → deterministic calculations → explanation in which every number is a traceable fact → explicit limitations and next steps. Supported by an anomaly monitor, history, exportable reports, a daily briefing and CSV import.

## 5. User stories and acceptance criteria (v1)

| # | Story | Acceptance criteria | Status |
|---|---|---|---|
| U1 | As an analyst I ask "Why did conversions fall last week?" and get the drivers. | Plan shows metric, periods (equal length) and segments; SQL passes validation; result rows shown; segment contributions sum exactly to the total change; summary names the largest contributor. | Done, e2e-tested |
| U2 | As a user I can see why I should trust a number. | Every number in the narrative is a fact chip linked to a computed fact; unverifiable numbers block the LLM draft (fallback narrative). | Done, unit + eval |
| U3 | As a user I'm told what the analysis can't tell me. | Limitations include missing days, low samples, tracking gaps, attribution conventions, demo mode, synthetic data. | Done |
| U4 | As a user I can inspect the SQL and pipeline. | SQL inspector shows executed SQL, each validation check, attempts, cross-check result, step timings, LLM usage. | Done |
| U5 | As a user I can't damage data, even by trying. | DML/DDL/multi-statement/catalog/unknown-function queries rejected before the DB; reader role cannot write. | Done, 30/30 attack corpus |
| U6 | As a user I can triage anomalies. | Filter by date/platform/metric/severity/status; set New/Investigating/Resolved/Not actionable; persisted per user. | Done, e2e-tested |
| U7 | As a user I can reopen, re-run, save and export. | History search/filter; stored vs fresh run clearly labelled; Markdown + PDF export; copy summary. | Done, e2e-tested |
| U8 | As a user I can analyse my own CSV. | Mapping, type/duplicate/missing checks, clear errors, private dataset, anomaly detection on import. | Done |
| U9 | As a user without an API key I can still use the product. | Demo mode works end-to-end and is labelled; zero LLM calls recorded. | Done |
| U10 | As a user I get a daily briefing on demand. | KPI changes ≥10%, new anomalies, freshness/quality issues, campaigns to investigate, open items. | Done (user-triggered) |

## 6. MVP scope and non-goals

**In scope:** single-tenant-per-user web app; campaign-day marketing data; the 10-step pipeline; anomaly monitor; history; reports; briefing; CSV import; demo mode; auth and per-user isolation; evaluation harness.

**Non-goals for v1:** live ad-platform connectors (shown as "not available yet"), causal inference, forecasting, scheduled briefings, team workspaces/sharing, arbitrary warehouse schemas, ML anomaly models, chat memory across investigations.

## 7. Prioritisation rationale

Ordered by *trust before breadth*: the riskiest assumption is that users will trust AI-generated analysis at all. So the first vertical slice was the safe pipeline with verifiable numbers (U1, U2, U5) before UI breadth. Anomalies and history (U6, U7) come next because they create the reason to come back. Connectors were cut: CSV covers the learning goal at a fraction of the cost and risk.

| Feature | Value (assumed) | Effort | Risk reduced | Decision |
|---|---|---|---|---|
| Safe SQL + fact verification | High | High | Trust, safety | v1 core |
| Contribution analysis | High | Medium | "Why" questions | v1 core |
| Anomaly monitor | Medium-high | Medium | Proactive value | v1 |
| CSV import | Medium | Medium | Works on real data | v1 |
| Live connectors | High | High (OAuth, quotas) | — | Roadmap |
| Scheduled briefing | Medium | Medium (worker) | Habit | Roadmap |

## 8. Product metrics (to instrument; none measured yet)

- **North star (proposed):** investigations per active user per week that end in a *saved, exported or acted-on* result.
- **Trust:** % of investigations where the user opens the SQL inspector or evidence; % re-asked/refined immediately (proxy for wrong interpretation).
- **Quality guard rails:** execution success rate, validator rejection rate, LLM-draft fallback rate, unverified-number rate (must stay 0 on display), p95 latency.
- **Retention:** week-2 return rate; anomalies triaged per user.

## 9. Risks and mitigations

| Risk | Mitigation in v1 |
|---|---|
| Wrong interpretation answered confidently | Plan, periods, filters shown above every answer; ambiguity → clarification; held-out eval tracks it (demo: 50%) |
| Hallucinated numbers | Fact placeholders + literal-number verification + deterministic fallback |
| Unsafe SQL / data exfiltration | AST allowlists, read-only role, RLS, timeouts, audit log |
| Misleading causality | Facts / calculations / hypotheses / actions separated; hedged language; causal-word warnings |
| Data-quality issues mistaken for performance | Missing-day and tracking-gap detection surfaced as limitations |
| LLM cost/latency | Three bounded calls, retry limits, rate limits, cost estimate recorded per run |

## 10. Experiment design (proposed, not run)

**Hypothesis:** showing fact chips and an explicit limitations section increases trust *without* reducing task speed.
- **Design:** A/B within a moderated usability study (n≈12 analysts/PMs), counterbalanced: (A) plain narrative answer, (B) AI Workmate evidence view. Same 6 tasks on the synthetic dataset, two with a planted data-quality trap (missing days, tracking gap).
- **Primary metric:** correct decision rate on trap tasks. **Secondary:** time to answer, self-reported confidence calibration (confidence vs correctness), SQL-inspector usage.
- **Success threshold (hypothesis):** ≥30 pp improvement in trap-task correctness with ≤20% time increase.
- **Risks:** small n, learning effects (counterbalancing), synthetic data realism.

## 11. Open questions

- Is campaign-day grain enough, or do users immediately need ad-set/creative grain?
- How often do users want to see the SQL vs just know it exists?
- What is the acceptable latency for an LLM-backed investigation in practice?
