# API specification

Interactive OpenAPI docs: `GET /docs` (Swagger) and `GET /openapi.json` on the API server.

**Auth:** session cookie `aw_session` (httpOnly, SameSite=Lax) set by the auth endpoints, or `Authorization: Bearer <token>`. Cookie-authenticated `POST/PATCH/DELETE` requests must send `X-Requested-With: aiworkmate`.

**Errors:** always `{"error": {"code": "...", "message": "...", "request_id": "...", "details"?: ...}}`. Raw database errors and prompts are never returned. Every response carries `X-Request-ID`.

**Pagination:** `?limit=&offset=` → `{items, total, limit, offset}`.

| Method | Path | Purpose | Notes |
|---|---|---|---|
| GET | `/health` | DB connectivity for both roles + mode | public |
| GET | `/api/system/status` | mode, provider/model (never the key), limits, detector, connectors | |
| POST | `/api/auth/register` | `{email, password(≥10), display_name}` → session | 409 if taken; rate-limited |
| POST | `/api/auth/login` | `{email, password}` → session | 401 generic message; rate-limited |
| POST | `/api/auth/demo` | Session for the shared demo account | only if `ALLOW_DEMO_LOGIN=true` |
| POST | `/api/auth/logout` | Clears cookie | |
| GET / PATCH | `/api/auth/me` | Profile; update `display_name`, `reporting_timezone` (IANA), `anomaly_sensitivity`, `active_dataset_id` | dataset access checked |
| GET | `/api/schema` | Approved tables, columns, types, relationships | `dataset_id` hidden |
| GET | `/api/metric-definitions` | Metric registry | public |
| GET | `/api/metrics/overview?days=7&series_days=60&dataset_id=` | KPIs vs previous period, daily series, open anomalies, recent investigations, freshness | |
| POST | `/api/analyses` | `{question(3–500), dataset_id?, parent_id?}` → full investigation (201) | rate-limited per user (429) |
| GET | `/api/analyses?q=&status=&saved=&intent=` | History (paginated, searchable) | own only |
| GET | `/api/analyses/{id}` | Stored investigation (`result_is_historical: true`) | 404 if not owner |
| PATCH | `/api/analyses/{id}` | `{saved?, title?}` | |
| DELETE | `/api/analyses/{id}` | Delete | 204 |
| POST | `/api/analyses/{id}/retry` | Re-run the question on current data → new linked record | rate-limited |
| GET | `/api/analyses/{id}/export?format=markdown\|pdf` | Download | |
| GET | `/api/anomalies?date_from=&date_to=&platform=&metric=&severity=&status=&kind=&dataset_id=` | Detections visible at the user's sensitivity + status counts + facets | |
| PATCH | `/api/anomalies/{id}` | `{status: new\|investigating\|resolved\|not_actionable, note?}` | per-user; 409 on invalid transition |
| POST | `/api/anomalies/detect?dataset_id=` | Re-run detection | own datasets only |
| GET | `/api/reports?kind=` | Saved reports | |
| POST | `/api/reports` | `{analysis_id}` or `{kind: "briefing"}` → Markdown snapshot | |
| GET / DELETE | `/api/reports/{id}` | Read / delete | |
| GET | `/api/reports/{id}/export?format=markdown\|pdf` | Download | |
| POST | `/api/briefings?dataset_id=` | Generate (not save) today's briefing | deterministic |
| GET | `/api/data-sources` | Accessible datasets with freshness + connector registry | |
| GET | `/api/data-sources/{id}/preview` | Campaigns + latest rows | |
| POST | `/api/data-sources/upload` | multipart `file` (.csv ≤ 10 MB, ≤ 200k rows) → `upload_id`, inferred columns, suggested mapping, preview | |
| POST | `/api/data-sources/imports/{upload_id}` | `{mapping, dataset_name, reporting_timezone}` → import summary (201) | validation errors as 422 with `details[]`; demo account 403 |
| DELETE | `/api/data-sources/{id}` | Delete own upload | 204 |

## Investigation object (abridged)

```json
{
  "id": 21, "question": "Why did conversions fall last week?", "status": "succeeded", "mode": "demo",
  "intent": "compare", "saved": false, "result_is_historical": false,
  "data_as_of": "2026-10-18", "current_data_as_of": "2026-10-18", "duration_ms": 68,
  "plan": {"intent": "compare", "metrics": ["conversions"], "time_range": {"preset": "last_week"},
           "comparison": "previous_period", "group_by": ["campaign"], "filters": []},
  "generated_sql": "SELECT CASE WHEN m.date BETWEEN ...",
  "sql_validation": {"ok": true, "checks": [{"check": "select_only", "passed": true}, "..."],
                     "tables": ["campaign_daily_metrics", "campaigns"], "limit_applied": 1000},
  "result": {"rows": ["..."], "row_count": 18, "periods": {"current": {"start": "2026-10-12", "end": "2026-10-18"}},
             "calculations": {"key_metrics": ["..."], "contributions": {"conversions": {"method": "...", "segments": ["..."]}},
                              "facts": [{"id": "total.conversions.pct_change", "display": "−3.1%", "value": -3.07}],
                              "charts": [{"type": "bar", "title": "Contribution to Conversions change by campaign"}]},
             "checks": {"crosscheck": {"matched": null, "note": "not applicable: query built deterministically"}}},
  "explanation": {"source": "deterministic", "summary": {"text": "...", "parts": [{"type": "fact", "fact_id": "..."}]},
                  "observed_facts": [], "contributions": [], "possible_explanations": [], "recommended_actions": [],
                  "computed_limitations": [], "verification": {"passed": true, "numeric_tokens_checked": 0}},
  "pipeline_trace": {"steps": [{"step": 1, "name": "Schema discovery", "status": "ok", "duration_ms": 3}]},
  "llm_usage": {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0}
}
```

Status values: `succeeded`, `failed`, `needs_clarification`, `unsupported`, `rejected`.
