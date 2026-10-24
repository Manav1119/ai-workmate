# Product roadmap

Sequenced by the riskiest open assumption first. Dates are intentionally omitted; each stage has an exit criterion instead.

## Now: validate trust and interpretation

| Item | Why | Exit criterion |
|---|---|---|
| Run the evaluation in LLM mode (Anthropic + an OpenAI-compatible model) | Only demo mode has been measured | `EVALUATION_RESULTS.md` has measured LLM correctness, held-out correctness, p50/p95 latency and cost per analysis |
| Grow the held-out set to 50+ paraphrases written by other people | Current held-out set is 10 questions by one author | Held-out set reviewed by ≥3 people; reported separately |
| Clarify-before-answer policy | Demo mode answered some questions confidently but wrongly | When interpretation confidence is low, ask instead of answer; measure clarification rate vs wrong-answer rate |
| Moderated usability test (see PRD §10) | Trust hypothesis is untested | ≥8 sessions; trap-task correctness and time recorded |

## Next: make it useful every week

- **Scheduled briefings** with a real background worker (not frontend timers) and email/Slack delivery.
- **Anomaly precision:** require persistence for low-severity flags, group simultaneous flags per campaign into one alert, learn per-campaign noise.
- **Saved views / follow-ups:** "watch this metric for this campaign" turns an investigation into a monitor.
- **Deeper segments:** ad set / creative grain once a connector provides it.

## Later: connect real data

- Connector interface implementations: Google Ads, Meta Ads (OAuth, quotas, incremental sync), warehouse (read-only role on the customer's DB).
- Team workspaces: shared datasets, roles, comments on investigations, audit export.
- Experiment helper: power calculations and pre/post comparisons with explicit causal caveats.

## Explicitly not planned

- Free-form SQL editor (contradicts the safety model).
- Auto-applying recommendations to ad platforms.
- Causal claims without an experimental or quasi-experimental design.
