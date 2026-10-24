from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text

from app.db import app_tx
from app.errors import ApiError
from app.routers.analyses import load_analysis
from app.schemas import ReportCreate, ReportOut
from app.security.auth import CurrentUser, current_user, dataset_for_user
from app.security.rate_limit import limiter
from app.services.briefing import build_briefing
from app.services.reports import analysis_to_markdown, markdown_to_pdf

router = APIRouter(tags=["reports"])


def _row(r) -> dict:
    d = dict(r)
    d["created_at"] = d["created_at"].isoformat()
    d["data_as_of"] = d["data_as_of"].isoformat() if d.get("data_as_of") else None
    return d


def _load(rid: int, user: CurrentUser) -> dict:
    with app_tx() as c:
        r = c.execute(text("SELECT * FROM app.reports WHERE id = :id AND user_id = :u"), {"id": rid, "u": user.id}
                      ).mappings().first()
    if not r:
        raise ApiError(404, "report_not_found", "Report not found.")
    return _row(r)


@router.get("/api/reports")
def list_reports(kind: str | None = Query(None, pattern="^(investigation|briefing)$"),
                 limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 user: CurrentUser = Depends(current_user)) -> dict:
    params = {"u": user.id, "lim": limit, "off": offset, "k": kind}
    cond = "user_id = :u" + (" AND kind = :k" if kind else "")
    with app_tx() as c:
        total = c.execute(text(f"SELECT COUNT(*) FROM app.reports WHERE {cond}"), params).scalar()
        rows = c.execute(text(f"SELECT id, kind, title, analysis_id, data_as_of, created_at, LEFT(markdown, 400) AS markdown"
                              f" FROM app.reports WHERE {cond} ORDER BY created_at DESC, id DESC LIMIT :lim OFFSET :off"),
                         params).mappings().all()
    return {"items": [_row(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/api/reports", status_code=201, response_model=ReportOut)
def create_report(body: ReportCreate, user: CurrentUser = Depends(current_user)) -> ReportOut:
    if body.kind == "investigation":
        if body.analysis_id is None:
            raise ApiError(422, "analysis_required", "analysis_id is required for an investigation report.")
        a = load_analysis(body.analysis_id, user)
        md, title, asof, aid = analysis_to_markdown(a), body.title or a.get("title") or a["question"], a.get("data_as_of"), a["id"]
    else:
        limiter.check(f"briefing:{user.id}", 10)
        ds = dataset_for_user(user, body.dataset_id)
        if ds["last_date"] is None:
            raise ApiError(422, "no_data", "The dataset has no data yet.")
        b = build_briefing(user, ds)
        md, title, asof, aid = b["markdown"], body.title or f"Daily briefing — {b['anchor_date']}", ds["last_date"], None
    with app_tx() as c:
        r = c.execute(
            text("INSERT INTO app.reports (user_id, analysis_id, kind, title, markdown, data_as_of)"
                 " VALUES (:u, :a, :k, :t, :m, :d) RETURNING *"),
            {"u": user.id, "a": aid, "k": body.kind, "t": title[:120], "m": md, "d": asof},
        ).mappings().one()
    return ReportOut(**_row(r))


@router.get("/api/reports/{rid}", response_model=ReportOut)
def get_report(rid: int, user: CurrentUser = Depends(current_user)) -> ReportOut:
    return ReportOut(**_load(rid, user))


@router.delete("/api/reports/{rid}", status_code=204)
def delete_report(rid: int, user: CurrentUser = Depends(current_user)) -> Response:
    _load(rid, user)
    with app_tx() as c:
        c.execute(text("DELETE FROM app.reports WHERE id = :id AND user_id = :u"), {"id": rid, "u": user.id})
    return Response(status_code=204)


@router.get("/api/reports/{rid}/export")
def export_report(rid: int, format: str = Query("markdown", pattern="^(markdown|pdf)$"),
                  user: CurrentUser = Depends(current_user)) -> Response:
    r = _load(rid, user)
    name = f"ai-workmate-report-{rid}"
    if format == "pdf":
        return Response(markdown_to_pdf(r["markdown"], r["title"]), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return Response(r["markdown"], media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


@router.post("/api/briefings")
def generate_briefing(dataset_id: int | None = None, user: CurrentUser = Depends(current_user)) -> dict:
    limiter.check(f"briefing:{user.id}", 10)
    ds = dataset_for_user(user, dataset_id)
    if ds["last_date"] is None:
        raise ApiError(422, "no_data", "The dataset has no data yet.")
    return build_briefing(user, ds)
