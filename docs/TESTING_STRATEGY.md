# Testing strategy

Principle: **test the things that would make a user trust a wrong answer**, against real infrastructure where it matters (Postgres roles and RLS cannot be mocked meaningfully).

## Layers

| Layer | Tool | Count (latest run) | What it covers |
|---|---|---|---|
| Unit (no database) | pytest | 102 | metric maths, ratio-of-sums vs averaged ratios, % change edge cases, period logic and timezone boundaries, LMDI exactness (randomised), SQL validator (7 safe + 35 unsafe cases, limit clamping, comment stripping), explanation verification and LLM-output schema validation, seed determinism, anomaly ground truth and negative controls |
| Integration (real Postgres) | pytest | 49 | reader-role permissions and RLS, executor timeout/truncation, unsafe SQL never reaching the DB, LLM pipeline with mocked provider HTTP (happy path, repair, fail-closed, cross-check, unverifiable-number fallback, invalid plans, provider errors), REST API (auth, CSRF, isolation, lifecycle, anomalies, reports, briefing, limits, rate limiting), CSV import (mapping, duplicates, types, formula injection, timezone conversion, file rejection, row limits) |
| Frontend unit | Vitest + Testing Library | 9 | formatting (units, minus signs, n/a for undefined), direction-aware change colours, investigate-question builder, fact-chip rendering, Markdown renderer safety |
| End-to-end | Playwright (Chromium) | 3 | full investigation workflow (below), unsafe prompt rejection, anomaly status persistence |
| Evaluation | `eval/run_eval.py` | 77 questions + 35 SQL | correctness vs independent oracle, execution success, traceability, evidence coverage, latency, cost, attack corpus, anomaly P/R |
| Container | docker compose | — | images build, migrations + seed on start, health checks, demo login and analysis through the web proxy |

Total automated tests: **151 backend + 9 frontend unit + 3 e2e**, all passing on the latest run.

## The required end-to-end workflow

`frontend/e2e/investigation.spec.ts`:
1. open the dashboard (demo login) → 2. ask "Why did conversions fall last week?" → 3. submit →
4. SQL inspector shows SQL and >8 validation checks, none failed; API confirms `sql_validation.ok` →
5. query-result tab present; API `row_count > 0` →
6. summary contains the key-metric values from the stored result; ≥3 fact chips; the first chart bar equals current − comparison computed from the returned rows; summary names that segment →
7. save → 8. reopen from History (saved filter) and see "Stored result" → 9. export Markdown (contains summary and values) and PDF (`%PDF`).

## Notable test design choices

- **Independent oracle.** Evaluation expectations are computed with pandas from the seed CSVs, not by re-running app SQL, so a shared bug can't make both sides agree.
- **Mocked HTTP, real adapters.** LLM tests use `httpx.MockTransport` behind the real `AnthropicProvider`/`OpenAIProvider`, exercising request shape, tool-choice parsing, retries and auth errors. These doubles live only in tests; the app never fakes an LLM response.
- **Separate test database.** `workmate_test` reuses the configured role passwords (roles are cluster-wide) so tests never break a dev setup.
- **Fixed clock** for pipeline and eval runs to keep relative dates reproducible.

## Bugs these tests caught during the build

- Demo interpreter missed plurals ("conversion **rates**"), so the high-spend/low-CVR question ranked by the wrong metric (eval).
- Markdown and PDF renderers kept the `|---|---|` separator as a data row (Vitest).
- Vitest config type error broke `next build` type checking (Docker build).
- Shared Postgres roles meant the test bootstrap reset dev passwords (manual run → fixed in `conftest.py`).

## Not covered yet

Load testing, accessibility automation (axe), visual regression, live-LLM evaluation, multi-instance rate limiting, browser matrix beyond Chromium.

## How to run

See the README "Tests" section. CI (`.github/workflows/ci.yml`) runs backend tests against a Postgres service, the evaluation in demo mode, frontend lint/typecheck/unit/build, Playwright e2e against live servers, and a compose build.
