# Case study template: AI Workmate

Use this to write the portfolio case study. Replace every `[bracket]`. Keep claims tied to evidence in this repo; mark anything else as an assumption.

---

## 1. One-line summary

[e.g. I built an AI analyst that answers "why did this metric move?" with numbers that trace back to validated, read-only SQL.]

## 2. The problem

- Who: [persona from USER_PERSONAS.md — say these are assumptions unless you've interviewed people]
- Pain: [time spent on SQL and explanations; untrustworthy AI answers]
- Why now: [LLMs make NL→SQL possible; trust is the bottleneck]

## 3. My role and constraints

- Role: [PM + builder]
- Constraints: [solo, synthetic data only, no paid API key during build, N weeks]

## 4. Key product decisions

Pick 3 from TRADEOFFS_AND_LEARNINGS.md. For each: options considered → decision → why → what it cost.

1. [Facts-as-placeholders instead of free-text numbers]
2. [Safety in layers instead of prompt rules]
3. [Honest demo mode instead of hiding the product]

## 5. What I built

- Screenshot: `docs/screenshots/03-analyst-why-conversions-fell.png`
- Screenshot: `docs/screenshots/04-fact-chip-tooltip.png`
- Demo recording: `docs/screenshots/demo-walkthrough.webm`
- Architecture: SYSTEM_ARCHITECTURE.md diagram

## 6. How I measured it

| Metric | Target (hypothesis) | Result | Evidence |
|---|---|---|---|
| Correctness on supported questions (demo) | ≥ 90% | [from EVALUATION_RESULTS.md] | eval/results/latest_demo.json |
| Correctness on held-out paraphrases (demo) | — | [ ] | same |
| Attack corpus rejected | 100% | [ ] | same |
| Numbers traceable | 100% | [ ] | same |
| Anomaly recall / precision (balanced) | — | [ ] | same |
| LLM-mode correctness | ≥ 90% | [not measured / measured on DATE with MODEL] | |

State test-set size and the in-sample caveat.

## 7. What went wrong and what I learned

[Pick 2–3 from TRADEOFFS_AND_LEARNINGS.md "Learnings", e.g. the CPA decomposition trap, quiet wrong answers on held-out questions.]

## 8. What I'd do next

[From PRODUCT_ROADMAP.md "Now": LLM-mode eval, clarify-before-answer, usability test.]

## 9. Do not claim

- user numbers, revenue, adoption or "production-ready" — none exist;
- that the validator is complete — it's tested against a corpus, not proven;
- LLM-mode results unless you've run the eval with a key and committed the output.
