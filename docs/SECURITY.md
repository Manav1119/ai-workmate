# Security

Threat model in one line: **a user (or a model acting on a user's words) tries to read data they shouldn't, change data, exhaust resources, or get the system to state false numbers.** Controls are layered so no single layer — and never the prompt — is the boundary.

## SQL safety (defence in depth)

| Layer | Control | Where |
|---|---|---|
| 1 Parse | sqlglot PostgreSQL parser; unparseable SQL rejected | `sqlsafe/validator.py` |
| 2 Statement | exactly one statement; root must be SELECT / UNION / INTERSECT / EXCEPT | validator |
| 3 Constructs | rejects DML/DDL anywhere in the tree (incl. data-modifying CTEs), `SELECT INTO`, `FOR UPDATE`, COPY, SET, commands (EXPLAIN, CREATE ROLE…), VALUES, LATERAL, table functions, recursive CTEs, `SELECT *` | validator |
| 4 Functions | allowlist of aggregate/arithmetic/date functions; `pg_sleep`, `set_config`, `current_setting`, `pg_read_file`, `lo_import`, `dblink`, `generate_series` etc. rejected; `CURRENT_DATE`/`NOW()` rejected (reproducibility) | validator |
| 5 Tables/schemas | only `analytics.campaigns` and `analytics.campaign_daily_metrics`; no other schema, catalog or cross-database reference | validator |
| 6 Identifiers | scope-aware resolution of every column against the real approved schema (sqlglot `qualify`); unknown and hidden columns (`dataset_id`) rejected | validator + `catalog.discover_catalog` |
| 7 Limits | 8k chars, node/join/nesting caps, integer-literal LIMIT clamped to `QUERY_ROW_LIMIT`, truncation detected | validator / executor |
| 8 Regeneration | executed SQL is regenerated from the validated AST (comments dropped) | validator |
| 9 Role | `workmate_reader`: LOGIN, NOSUPERUSER, NOBYPASSRLS, `SELECT` on two tables only, no `app` schema access, `default_transaction_read_only`, `statement_timeout` | migrations 003 |
| 10 Transaction | `SET TRANSACTION READ ONLY`, per-transaction timeout (`QUERY_TIMEOUT_MS`) | executor |
| 11 Isolation | row-level security: reader sees only rows where `dataset_id = current_setting('app.dataset_id')`, set by the executor per transaction (and unreachable from validated SQL) | migrations 001/003 |
| 12 Audit | every attempt (rejected or executed) in `app.query_audit` with hash, reasons, rows, timing | executor |
| 13 Repair limit | at most `SQL_REPAIR_ATTEMPTS` LLM retries; validation is never bypassed; persistent failures fail closed | orchestrator |

Tests prove unsafe SQL never reaches the database: `tests/test_db_security.py::test_unvalidated_sql_never_reaches_database` replaces the reader engine with one that raises, then pushes rejected queries through the executor. The evaluation's 30-query attack corpus is rejected 30/30.

Note: `default_transaction_read_only` is only a default (a session can request READ WRITE); grants are the real barrier and are tested (`test_reader_cannot_write_even_after_requesting_read_write`). `pg_catalog` is readable by every Postgres role; the validator blocks it, and the reader role holds no sensitive objects.

## Authentication and authorisation

- Passwords: bcrypt (cost 12), min length 10. Generic login errors. Login/register rate-limited per IP.
- Sessions: HS256 JWT (`JWT_SECRET`, 12 h) in an httpOnly, SameSite=Lax cookie (`COOKIE_SECURE=true` behind HTTPS); Bearer tokens for API clients.
- CSRF: cookie-authenticated writes require `X-Requested-With: aiworkmate`.
- Isolation: every investigation, report and anomaly state is filtered by `user_id`; other users' objects return **404** (existence is not revealed). Datasets: public synthetic or owned; checked on every request that takes `dataset_id`. Tested in `test_api.py::test_user_isolation` and `test_csv_import.py`.
- The demo account is shared by design; it cannot store uploads or rename itself, and the UI says its history is visible to others.

## LLM-specific risks

- **Keys** only in backend env (`SecretStr`), never logged (log redaction for `sk-…`, `password=`, DB URL passwords), never returned by `/api/system/status`.
- **Prompt injection via data**: the model only receives schema descriptions, campaign names and computed facts; campaign names are user data, so any SQL they inspire is still validated. Model output is parsed into Pydantic schemas; free text never executes.
- **Hallucinated numbers**: numbers must be fact placeholders; literal numbers are verified; failing drafts are replaced.
- **Cost/abuse**: per-user analysis rate limit, 3 calls per analysis plus bounded retries, timeouts, token usage recorded.

## Uploads

Extension + content checks (UTF-8 text, no NUL bytes), 10 MB / 200k rows / 50 columns caps, strict numeric/date parsing, negative-value and clicks>impressions checks, duplicate-grain rejection, **spreadsheet formula injection neutralised** (`=`, `+`, `-`, `@` prefixed with `'`), random upload IDs with strict format, staged files deleted after import, uploads private to the owner.

## Platform hardening

Request-ID middleware, JSON structured logs (no secrets), body-size limits (64 KB JSON, 10 MB upload) → 413, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, CORS restricted to configured origins, connection pooling with pre-ping, non-root containers, pinned Python dependencies and lockfile for npm, health checks.

## Known gaps

- Rate limiter is in-memory (single instance); use Redis or the gateway when scaling out.
- No account lockout / password reset / MFA; no email verification.
- JWTs are not revocable before expiry (logout clears the cookie only).
- No CSP header yet; Next.js inline runtime would need nonces.
- Audit log has no retention policy.
