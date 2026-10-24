# Evaluation report (demo mode)

Run at 2026-10-24T17:43:56+00:00 against the synthetic dataset `synthetic_demo_v1` with a fixed clock (2026-10-24T12:00:00+00:00).
Expected answers come from an independent pandas oracle over the seed CSVs, not from the app's SQL.

> **Demo mode:** no LLM API key was configured for this run. Interpretation is rule-based and narratives are templated. These numbers measure the deterministic pipeline (validation, execution, calculations, verification), **not** LLM text-to-SQL quality.

## Read this first

- The 53 'supported' benchmark questions were written by the same developer who wrote the rule-based demo interpreter, so demo-mode correctness on them is **in-sample** and overstates how well demo mode handles new phrasing. The 10 held-out paraphrases (written afterwards, never used for tuning) are the better estimate.
- Latency here excludes HTTP and LLM time. With an LLM configured, expect 3 sequential model calls per question.
- Test-set size is small (77 questions, one synthetic dataset). Treat results as a regression baseline, not a claim of production readiness.

## Headline metrics

| Metric | Target (hypothesis) | Measured |
|---|---|---|
| Correctness on supported questions | ≥ 90% | 100.0% (53 questions) |
| Correctness on held-out paraphrases (not used for tuning) | (no target set) | 50.0% (10 questions) |
| Execution success on supported questions | ≥ 95% | 100.0% |
| Correct handling of unsupported / ambiguous / unsafe | (no target set) | 100.0% (14 questions) |
| Displayed numeric claims traceable to validated results | 100% | 100.0% |
| Evidence coverage (SQL + result rows + facts + chart where applicable + limitations) | (no target set) | 100.0% |
| Median / p95 latency | median < 10 s | 21 ms / 27 ms |
| Estimated LLM cost per analysis | (no target set) | $0.0000 (0 LLM calls) |
| SQL attack corpus rejected by validator | 100% | 30/30 |
| Safe SQL corpus accepted | 100% | 5/5 |
| Analytics tables unchanged after unsafe prompts | yes | yes |

## By category

| Category | Questions | Correct |
|---|---:|---:|
| ambiguous | 3 | 3 |
| anomaly | 2 | 2 |
| date_comparison | 8 | 8 |
| driver_analysis | 7 | 7 |
| group_by | 7 | 7 |
| held_out_paraphrase | 10 | 5 |
| invalid | 1 | 1 |
| missing_data | 3 | 3 |
| ratio_metric | 8 | 8 |
| simple_aggregation | 10 | 10 |
| trend | 5 | 5 |
| unanswerable | 5 | 5 |
| unsafe | 5 | 5 |
| zero_denominator | 3 | 3 |

## Anomaly detection vs ground truth

Flags matched to a scenario if same campaign and overlapping the scenario window (±2 days). Precision counts every flag that is not part of a labelled scenario as a false positive (the synthetic noise has no other labelled events).

| Sensitivity | |z| ≥ | Flags | Precision | Scenario recall | Missed | Negative controls violated |
|---|---:|---:|---:|---:|---|---|
| conservative | 5.0 | 15 | 40.0% | 100.0% | none | none |
| balanced | 4.0 | 27 | 44.4% | 100.0% | none | none |
| sensitive | 3.0 | 73 | 20.5% | 100.0% | none | none |

## Failure cases (5)

- **ho-05** (held_out_paraphrase) “Break down clicks per campaign for October so far” → succeeded: period ['2026-10-01', '2026-10-31'] != ['2026-10-01', '2026-10-18']
- **ho-06** (held_out_paraphrase) “What share of spend went to Meta last week?” → succeeded: segment Google Ads: None != oracle 67484.39; segments [] != ['Google Ads', 'LinkedIn', 'Meta', 'TikTok']
- **ho-07** (held_out_paraphrase) “Are conversions trending up over the last 30 days?” → succeeded: series dates differ (0 vs 30); 30 series values differ, e.g. 2026-09-19: None vs 739.0
- **ho-08** (held_out_paraphrase) “Spend for Google over the last 2 weeks” → succeeded: period ['2026-10-12', '2026-10-18'] != ['2026-10-05', '2026-10-18']; current 67484.39 != oracle 135062.31
- **ho-10** (held_out_paraphrase) “What made CPA worse last week?” → succeeded: no contribution analysis

## All questions

| ID | Category | Status | Correct | Latency (ms) |
|---|---|---|---|---:|
| agg-01 | simple_aggregation | succeeded | yes | 56 |
| agg-02 | simple_aggregation | succeeded | yes | 26 |
| agg-03 | simple_aggregation | succeeded | yes | 22 |
| agg-04 | simple_aggregation | succeeded | yes | 26 |
| agg-05 | simple_aggregation | succeeded | yes | 21 |
| agg-06 | simple_aggregation | succeeded | yes | 23 |
| agg-07 | simple_aggregation | succeeded | yes | 20 |
| agg-08 | simple_aggregation | succeeded | yes | 24 |
| agg-09 | simple_aggregation | succeeded | yes | 88 |
| agg-10 | simple_aggregation | succeeded | yes | 23 |
| ratio-01 | ratio_metric | succeeded | yes | 23 |
| ratio-02 | ratio_metric | succeeded | yes | 19 |
| ratio-03 | ratio_metric | succeeded | yes | 21 |
| ratio-04 | ratio_metric | succeeded | yes | 21 |
| ratio-05 | ratio_metric | succeeded | yes | 20 |
| ratio-06 | ratio_metric | succeeded | yes | 20 |
| ratio-07 | ratio_metric | succeeded | yes | 22 |
| ratio-08 | ratio_metric | succeeded | yes | 23 |
| cmp-01 | date_comparison | succeeded | yes | 23 |
| cmp-02 | date_comparison | succeeded | yes | 22 |
| cmp-03 | date_comparison | succeeded | yes | 23 |
| cmp-04 | date_comparison | succeeded | yes | 21 |
| cmp-05 | date_comparison | succeeded | yes | 21 |
| cmp-06 | date_comparison | succeeded | yes | 22 |
| cmp-07 | date_comparison | succeeded | yes | 19 |
| cmp-08 | date_comparison | succeeded | yes | 21 |
| drv-01 | driver_analysis | succeeded | yes | 24 |
| drv-02 | driver_analysis | succeeded | yes | 27 |
| drv-03 | driver_analysis | succeeded | yes | 24 |
| drv-04 | driver_analysis | succeeded | yes | 27 |
| drv-05 | driver_analysis | succeeded | yes | 26 |
| drv-06 | driver_analysis | succeeded | yes | 24 |
| drv-07 | driver_analysis | succeeded | yes | 23 |
| grp-01 | group_by | succeeded | yes | 21 |
| grp-02 | group_by | succeeded | yes | 24 |
| grp-03 | group_by | succeeded | yes | 23 |
| grp-04 | group_by | succeeded | yes | 26 |
| grp-05 | group_by | succeeded | yes | 20 |
| grp-06 | group_by | succeeded | yes | 20 |
| grp-07 | group_by | succeeded | yes | 19 |
| trd-01 | trend | succeeded | yes | 24 |
| trd-02 | trend | succeeded | yes | 24 |
| trd-03 | trend | succeeded | yes | 25 |
| trd-04 | trend | succeeded | yes | 25 |
| trd-05 | trend | succeeded | yes | 19 |
| zero-01 | zero_denominator | succeeded | yes | 20 |
| zero-02 | zero_denominator | succeeded | yes | 19 |
| zero-03 | zero_denominator | succeeded | yes | 25 |
| miss-01 | missing_data | succeeded | yes | 21 |
| miss-02 | missing_data | succeeded | yes | 35 |
| miss-03 | missing_data | succeeded | yes | 22 |
| anom-01 | anomaly | succeeded | yes | 7 |
| anom-02 | anomaly | succeeded | yes | 8 |
| amb-01 | ambiguous | needs_clarification | yes | 4 |
| amb-02 | ambiguous | needs_clarification | yes | 3 |
| amb-03 | ambiguous | needs_clarification | yes | 3 |
| inv-01 | unanswerable | unsupported | yes | 3 |
| inv-02 | unanswerable | unsupported | yes | 4 |
| inv-03 | unanswerable | unsupported | yes | 4 |
| inv-04 | unanswerable | unsupported | yes | 4 |
| inv-05 | invalid | needs_clarification | yes | 5 |
| inv-06 | unanswerable | unsupported | yes | 3 |
| unsafe-01 | unsafe | rejected | yes | 4 |
| unsafe-02 | unsafe | rejected | yes | 3 |
| unsafe-03 | unsafe | rejected | yes | 2 |
| unsafe-04 | unsafe | rejected | yes | 2 |
| unsafe-05 | unsafe | rejected | yes | 3 |
| ho-01 | held_out_paraphrase | succeeded | yes | 21 |
| ho-02 | held_out_paraphrase | succeeded | yes | 21 |
| ho-03 | held_out_paraphrase | succeeded | yes | 20 |
| ho-04 | held_out_paraphrase | succeeded | yes | 22 |
| ho-05 | held_out_paraphrase | succeeded | no | 23 |
| ho-06 | held_out_paraphrase | succeeded | no | 20 |
| ho-07 | held_out_paraphrase | succeeded | no | 17 |
| ho-08 | held_out_paraphrase | succeeded | no | 25 |
| ho-09 | held_out_paraphrase | succeeded | yes | 24 |
| ho-10 | held_out_paraphrase | succeeded | no | 20 |
