# Data dictionary and metric definitions

The source of truth in code is `backend/app/analytics/metrics.py` (served at `GET /api/metric-definitions`) and `backend/app/sqlsafe/catalog.py` (served at `GET /api/schema`).

## Tables (schema `analytics`)

### `campaigns` — grain: one row per campaign per dataset. PK `(dataset_id, campaign_id)`

| Column | Type | Description |
|---|---|---|
| campaign_id | text | Campaign identifier (join key) |
| campaign_name | text | Human-readable name |
| platform | text | `Google Ads`, `Meta`, `TikTok`, `LinkedIn` in the demo |
| objective | text | `Conversions`, `Leads`, `Sales`, `Awareness` |
| start_date | date | Campaign start |
| status | text | `active` or `paused` |

### `campaign_daily_metrics` — grain: one row per campaign per reporting-timezone date. PK `(dataset_id, date, campaign_id)`

| Column | Type | Description |
|---|---|---|
| date | date | Reporting date in the dataset's reporting timezone |
| campaign_id | text | FK → campaigns |
| spend | numeric(14,2) | Media cost, USD, ≥ 0 |
| impressions | bigint | ≥ 0 |
| clicks | bigint | Link clicks, ≥ 0 |
| conversions | bigint | Attributed conversion events, de-duplicated at source, ≥ 0 |
| revenue | numeric(14,2) | Attributed conversion value, USD, ≥ 0 |

`dataset_id` exists on both tables but is **not** part of the approved schema: generated SQL cannot reference it; isolation is enforced by row-level security.

**Double counting** is prevented structurally: the primary key allows exactly one row per campaign-day, and CSV imports reject duplicate `(date, campaign)` rows.

## Metrics

All ratio metrics are **ratios of aggregate totals** over the period and segment. Daily ratios are never averaged.

| Key | Label | Formula | Source columns | Aggregation | Zero / missing handling | Min sample (anomaly + caveats) |
|---|---|---|---|---|---|---|
| spend | Spend | SUM(spend) | spend | sum | 0 is valid | — |
| impressions | Impressions | SUM(impressions) | impressions | sum | 0 is valid | — |
| clicks | Clicks | SUM(clicks) | clicks | sum | 0 is valid | — |
| conversions | Conversions | SUM(conversions) | conversions | sum | 0 is valid; 0 with normal clicks is checked as a tracking gap | — |
| revenue | Revenue | SUM(revenue) | revenue | sum | 0 is valid | — |
| ctr | CTR | SUM(clicks) / SUM(impressions) | clicks, impressions | ratio of sums | undefined (null) if impressions = 0 | 1,000 impressions |
| conversion_rate | Conversion rate | SUM(conversions) / SUM(clicks) — **denominator is clicks** | conversions, clicks | ratio of sums | undefined if clicks = 0 | 200 clicks |
| cpc | CPC | SUM(spend) / SUM(clicks) | spend, clicks | ratio of sums | undefined if clicks = 0 | 100 clicks |
| cpa | CPA | SUM(spend) / SUM(conversions) | spend, conversions | ratio of sums | undefined if conversions = 0 (shown as "n/a", never 0 or ∞) | 10 conversions |
| roas | ROAS | SUM(revenue) / SUM(spend) | revenue, spend | ratio of sums | undefined if spend = 0 | $100 spend |
| aov | AOV | SUM(revenue) / SUM(conversions) | revenue, conversions | ratio of sums | undefined if conversions = 0 | 10 conversions |

**Conversion event definition:** platform-attributed purchase (or lead, for lead-gen objectives) events as reported per campaign-day. Attribution window and model are the platform's; they may differ from backend orders (stated as a limitation).

**Missing data:** a campaign-day with no row is *missing*, not zero. Values are never imputed. Coverage is checked for every analysis and gaps are listed as limitations.

### Changes

- **Absolute change** = current − comparison.
- **Percentage change** = (current − comparison) / |comparison| × 100.
  - comparison = 0 and current = 0 → 0%;
  - comparison = 0 and current ≠ 0 → undefined ("comparison value is zero");
  - either value missing → undefined with a reason.
- Percentage-point changes are shown for rates (e.g. `−0.16 pp`).

### Time periods

- Relative ranges are resolved in code (never by the LLM) against the **anchor date** = min(latest date with data, today in the user's reporting timezone).
- Weeks are Monday–Sunday. `last_week` = the most recent *complete* week ending on or before the anchor. `this_week` = Monday of the anchor's week through the anchor (may be partial).
- Comparison `previous_period` = the same number of days immediately before; a full calendar month compares with the previous calendar month. `same_period_last_year` is also supported.
- The reporting timezone is a per-user setting (and per-dataset for imports). CSV timestamps are converted into calendar dates in the chosen timezone (naive timestamps = UTC).

### Contribution analysis

- Additive metrics: segment contribution = current − comparison (sums exactly to the total change).
- Ratio metrics (N/D): **LMDI decomposition**, exact and additive:
  `contribution_i = L(R1,R0) · (ΔN_i / L(N1,N0) − ΔD_i / L(D1,D0))`, where `L(a,b) = (a−b)/ln(a/b)`.
  Each contribution splits into a numerator effect (e.g. spend for CPA) and a denominator effect (conversions). If any total is zero, the simpler share form `N_i1/D_1 − N_i0/D_0` is used and noted.
- Notes are added for low samples, segments with undefined own ratios, and heavy offsetting (gross movement > 2.5× net).
- Contributions describe *where* a change happened, not *why*.

## Anomaly detection (`robust-dow-v1`)

| Element | Rule |
|---|---|
| Baseline | Previous 28 days with data (missing days skipped, never imputed); ≥ 21 baseline days required |
| Seasonality | Day-of-week factors from the previous 56 days for additive metrics |
| Expected | Median of de-seasonalised baseline × weekday factor; ratios use ratio of baseline sums |
| Spread | max(MAD × 1.4826, sampling-noise floor, 3% of level). Noise floor: Poisson for counts, binomial for CVR, conversion-count-based for spend/revenue/CPA/ROAS |
| Flag | \|robust z\| ≥ threshold **and** \|deviation\| ≥ 20% **and** minimum sample met |
| Sensitivity | conservative z ≥ 5, balanced z ≥ 4 (default), sensitive z ≥ 3 (per-user setting) |
| Episodes | Consecutive flagged days in the same direction are merged |
| Severity | high if \|z\| ≥ 8 and \|dev\| ≥ 40%; medium if \|z\| ≥ 6 or \|dev\| ≥ 40%; +1 level for episodes ≥ 3 days |
| Data quality | missing campaign-days (active campaigns only); tracking gap = 0 conversions with clicks ≥ 50% of normal and ≥ 8 expected conversions. Tracking-gap days are excluded from conversion-based baselines |

## Synthetic dataset and ground truth

`backend/seed/generate.py`, seed `20261018`, 2026-06-29 → 2026-10-18 (16 full weeks), 10 campaigns, 4 platforms, 1,065 campaign-day rows. Variation: ~100× size range, channel-specific weekday profiles, slow seasonal drift, multiplicative day noise, binomial clicks/conversions, gamma order values.

| Scenario | Campaign | What happened | Expected behaviour |
|---|---|---|---|
| S1 conversion decline | C003 Prospecting - Lookalike (Meta) | CVR × 0.52 from 2026-10-12, clicks unchanged | Top driver of last week's conversion/CPA/revenue change; CVR/CPA anomalies |
| S2 spend without revenue | C005 Spark Ads - UGC (TikTok) | Budget × 1.7 and CVR × 0.62 from 2026-09-28 | Spend/clicks/CPA anomalies; top ROAS-decline driver |
| S3 missing data | C007 Display - Remarketing | No rows 2026-09-14…20 | Missing-data anomaly; coverage limitation |
| S4 tracking discrepancy | C008 Shopping - Catalog | 0 conversions/revenue 2026-09-22…25, clicks normal | Tracking-gap anomaly; data-quality limitation |
| S5 low volume (negative control) | C006 Lead Gen (LinkedIn) | ~45 clicks/day | No ratio-metric anomalies |
| S6 paused (negative control) | C010 (TikTok) | Paused after 2026-08-31 | Not flagged as missing data |

Sample questions with real answers: [EXAMPLE_QUESTIONS.md](EXAMPLE_QUESTIONS.md). The 77-question benchmark with expected-value specs: `backend/eval/benchmark.json`.
