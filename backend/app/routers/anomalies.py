from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.analytics import anomalies as anomaly_engine
from app.db import app_tx
from app.errors import ApiError
from app.routers.meta import _anom_out
from app.schemas import AnomalyPatch
from app.security.auth import CurrentUser, current_user, dataset_for_user
from app.security.rate_limit import limiter
from app.services.datasets import run_anomaly_detection

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])

# Allowed workflow transitions (any state can be re-opened to 'new' or 'investigating').
TRANSITIONS = {
    "new": {"investigating", "resolved", "not_actionable"},
    "investigating": {"new", "resolved", "not_actionable"},
    "resolved": {"new", "investigating"},
    "not_actionable": {"new", "investigating"},
}


@router.get("")
def list_anomalies(
    dataset_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
    platform: str | None = Query(None, max_length=60), metric: str | None = Query(None, max_length=40),
    severity: str | None = Query(None, pattern="^(low|medium|high)$"),
    status: str | None = Query(None, pattern="^(new|investigating|resolved|not_actionable)$"),
    kind: str | None = Query(None, pattern="^(drop|spike|missing_data|tracking_gap)$"),
    include_all_sensitivities: bool = False,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(current_user),
) -> dict:
    ds = dataset_for_user(user, dataset_id)
    conds = ["a.dataset_id = :d"]
    params: dict = {"d": ds["id"], "u": user.id}
    if date_from:
        conds.append("a.episode_end >= :df")
        params["df"] = date_from
    if date_to:
        conds.append("a.anomaly_date <= :dt")
        params["dt"] = date_to
    if platform:
        conds.append("a.platform = :pl")
        params["pl"] = platform
    if metric:
        conds.append("a.metric = :m")
        params["m"] = metric
    if severity:
        conds.append("a.severity = :sv")
        params["sv"] = severity
    if kind:
        conds.append("a.kind = :k")
        params["k"] = kind
    if status:
        conds.append("COALESCE(s.status, 'new') = :st")
        params["st"] = status
    with app_tx() as c:
        rows = [dict(x) for x in c.execute(
            text("SELECT a.*, COALESCE(s.status, 'new') AS status, s.note, s.updated_at AS status_updated_at"
                 " FROM app.anomalies a LEFT JOIN app.anomaly_states s ON s.anomaly_id = a.id AND s.user_id = :u"
                 f" WHERE {' AND '.join(conds)} ORDER BY a.anomaly_date DESC,"
                 " CASE a.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.id"), params,
        ).mappings()]
        facets = c.execute(
            text("SELECT ARRAY_AGG(DISTINCT platform) AS platforms, ARRAY_AGG(DISTINCT metric) AS metrics,"
                 " MIN(anomaly_date) AS first, MAX(episode_end) AS last FROM app.anomalies WHERE dataset_id = :d"),
            {"d": ds["id"]},
        ).mappings().one()
    if not include_all_sensitivities:
        rows = [r for r in rows if anomaly_engine.visible(r["robust_z"], r["kind"], user.anomaly_sensitivity)]
    total = len(rows)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in TRANSITIONS}
    return {
        "items": [_anom_out(r) for r in rows[offset: offset + limit]], "total": total, "limit": limit, "offset": offset,
        "status_counts": counts, "sensitivity": user.anomaly_sensitivity,
        "facets": {"platforms": sorted(p for p in (facets["platforms"] or []) if p),
                   "metrics": sorted(m for m in (facets["metrics"] or []) if m),
                   "date_range": [_iso(facets["first"]), _iso(facets["last"])]},
        "detector": anomaly_engine.DETECTOR_VERSION,
    }


def _iso(v):
    return v.isoformat() if v else None


@router.patch("/{anomaly_id}")
def update_anomaly(anomaly_id: int, body: AnomalyPatch, user: CurrentUser = Depends(current_user)) -> dict:
    with app_tx() as c:
        a = c.execute(text("SELECT dataset_id FROM app.anomalies WHERE id = :id"), {"id": anomaly_id}).mappings().first()
        if not a:
            raise ApiError(404, "anomaly_not_found", "Anomaly not found.")
        dataset_for_user(user, a["dataset_id"])  # authorization
        cur = c.execute(text("SELECT status FROM app.anomaly_states WHERE anomaly_id = :a AND user_id = :u"),
                        {"a": anomaly_id, "u": user.id}).scalar() or "new"
        if body.status != cur and body.status not in TRANSITIONS[cur]:
            raise ApiError(409, "invalid_transition", f"Cannot move an anomaly from '{cur}' to '{body.status}'.")
        c.execute(
            text("INSERT INTO app.anomaly_states (anomaly_id, user_id, status, note, updated_at)"
                 " VALUES (:a, :u, :s, :n, now()) ON CONFLICT (anomaly_id, user_id) DO UPDATE SET"
                 " status = EXCLUDED.status, note = COALESCE(EXCLUDED.note, app.anomaly_states.note), updated_at = now()"),
            {"a": anomaly_id, "u": user.id, "s": body.status, "n": body.note},
        )
        row = dict(c.execute(
            text("SELECT a.*, s.status, s.note, s.updated_at AS status_updated_at FROM app.anomalies a JOIN"
                 " app.anomaly_states s ON s.anomaly_id = a.id AND s.user_id = :u WHERE a.id = :id"),
            {"id": anomaly_id, "u": user.id},
        ).mappings().one())
    return {**_anom_out(row), "previous_status": cur}


@router.post("/detect")
def redetect(dataset_id: int | None = None, user: CurrentUser = Depends(current_user)) -> dict:
    ds = dataset_for_user(user, dataset_id)
    if ds["owner_user_id"] != user.id:
        raise ApiError(403, "forbidden", "Detection can only be re-run on your own datasets.")
    limiter.check(f"detect:{user.id}", 5)
    return {"anomalies_detected": run_anomaly_detection(ds["id"])}
