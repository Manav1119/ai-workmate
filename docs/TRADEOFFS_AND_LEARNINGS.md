# Trade-offs and learnings

## Technical trade-offs

| Decision | Alternative | Why this way | Cost |
|---|---|---|---|
| LLM writes **additive SUMs only**; ratios computed in Python | Let the LLM compute CPA/ROAS in SQL | Removes averaged-ratio and divide-by-zero mistakes; enables a totals cross-check | Some questions (e.g. medians) are out of scope |
| **Fact placeholders** for every narrative number | Free-text answers with post-hoc number checks only | Traceability by construction; UI can render fact chips | Narrative is a bit stiffer; LLM must learn the placeholder format (prompt + retry + fallback) |
| **AST validator + least-privilege role + RLS** | Prompt rules, regex filters, or a read-only role alone | Each layer catches what the others miss; prompts are not a boundary | More code; some legitimate SQL (e.g. `SELECT *`, `CURRENT_DATE`) is rejected |
| **Independent deterministic cross-check** of LLM SQL totals | Trust the query if it validates | Validation proves *safety*, not *correctness*; the cross-check catches wrong date ranges/filters | Second query per analysis |
| **LMDI** for ratio-metric contributions | Simple share decomposition `N_i1/D1 − N_i0/D0` | The simple form barely attributes a CPA rise to a campaign whose *conversions* collapsed (its spend didn't change). LMDI splits numerator vs denominator effects exactly | Harder to explain; documented and labelled "convention-dependent" |
| **Statistical anomaly baseline** (robust z, weekday factors, sample gates) | ML models | Explainable, needs no training data, good recall on the scenarios | Precision 44% at default; misses gradual drifts |
| **Demo mode** that is honest about being rule-based | Hide the product until a key exists / fake LLM output | Portfolio reviewers can use it without keys; shares the whole safety + maths path | Keyword interpreter generalises poorly (50% held-out) |
| **Per-user anomaly states** on shared detections | States on the anomaly row | Demo dataset is shared; one user's triage must not change another's | Extra join |
| **Sync pipeline** in the request | Job queue | Simpler; demo-mode latency is ~20 ms, LLM ~3 calls | Long LLM calls hold a worker; queue needed at scale |
| **In-process rate limiter** | Redis | No extra infra for v1 | Single instance only (documented) |
| Store **aggregated result rows** (≤500) with each investigation | Store only the SQL and re-run | Reopening shows exactly what the user saw; rows are aggregated, not raw events | Storage growth; reruns are explicit |

## Learnings from building it

1. **Validation proves safety, not correctness.** A perfectly safe query can still use the wrong dates. The totals cross-check (tested with a deliberately shifted date range) is what turns "safe" into "probably right".
2. **The obvious decomposition answers the wrong question for CPA.** My first ratio decomposition attributed last week's CPA increase mainly to a TikTok campaign; the campaign whose conversions halved barely showed up. Seeing that output on the synthetic ground truth is what led to LMDI.
3. **The eval found a bug the unit tests didn't:** the rule interpreter matched "conversion" inside "conversion rates" (no plural), so a high-spend/low-CVR question was ranked by spend.
4. **Writing the benchmark next to the interpreter inflates scores.** In-sample: 100%. Held-out paraphrases written afterwards: 50%. Both numbers are reported; the held-out one is the honest one.
5. **Quiet failures are worse than loud ones.** The worst held-out misses *succeeded* — they answered a nearby question. That is why the plan, periods and filters sit above every answer, and why "clarify before answering" is first on the roadmap.
6. **Infrastructure details leak into correctness.** Postgres roles are cluster-wide, so the test bootstrap silently changed the dev role passwords; a Vitest config file broke `next build` type-checking only inside Docker. Both were found by actually running the stack end to end.
7. **Synthetic data needs adversarial design.** The first generator version put the tracking gap inside the comparison week, which hid the conversion decline in the totals. Ground-truth scenarios must be checked against the questions they're meant to test.

## Assumptions vs findings

| Statement | Type |
|---|---|
| Users will trust answers more when every number is traceable | Assumption (untested) |
| Analysts spend significant time explaining metric movements | Assumption (from the brief) |
| The pipeline returns oracle-exact numbers on the 53 in-sample questions in demo mode | Finding (measured) |
| Demo-mode interpretation is right on 5/10 held-out paraphrases | Finding (measured, small n) |
| The validator rejects 30/30 known attack patterns | Finding (measured; not a proof of completeness) |
| LLM mode will be more robust to phrasing than demo mode | Assumption (not yet measured) |
