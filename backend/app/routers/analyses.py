from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text

from app.config import get_settings
from app.db import app_tx
from app.errors import ApiError
from app.llm.base import LLMProvider
from app.llm.providers import get_provider
from app.pipeline.orchestrator import run_analysis
from app.schemas import AnalysisCreate, AnalysisOut, AnalysisPatch, AnalysisSummary, Page
from app.security.auth import CurrentUser, current_user, dataset_for_user
from app.security.rate_limit import limiter
from app.services.reports import analysis_to_markdown, markdown_to_pdf

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


def provider_dep() -> LLMProvider | None:
    return get_provider()


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def load_analysis(aid: int, user: CurrentUser) -> dict:
    with app_tx() as c:
        r = c.execute(
            text("SELECT a.*, d.name AS dataset_name, d.is_synthetic AS dataset_is_synthetic,"
                 " d.last_date AS current_data_as_of FROM app.analyses a JOIN app.datasets d ON d.id = a.dataset_id"
                 " WHERE a.id = :id AND a.user_id = :u"),
            {"id": aid, "u": user.id},
        ).mappings().first()
    if not r:
        raise ApiError(404, "analysis_not_found", "Investigation not found.")
    a = {k: _iso(v) for k, v in dict(r).items()}
    a["result_is_historical"] = True
    return a


def _out(a: dict) -> AnalysisOut:
    return AnalysisOut(**{k: a.get(k) for k in AnalysisOut.model_fields})


@router.post("", status_code=201, response_model=AnalysisOut)
def create_analysis(body: AnalysisCreate, user: CurrentUser = Depends(current_user),
                    provider: LLMProvider | None = Depends(provider_dep)) -> AnalysisOut:
    limiter.check(f"analysis:{user.id}", get_settings().analysis_rate_limit_per_minute)
    ds = dataset_for_user(user, body.dataset_id)
    if body.parent_id is not None:
        load_analysis(body.parent_id, user)
    aid = run_analysis(user=user, dataset=ds, question=body.question, provider=provider, parent_id=body.parent_id)
    a = load_analysis(aid, user)
    a["result_is_historical"] = False
    return _out(a)


@router.get("", response_model=Page[AnalysisSummary])
def list_analyses(
    q: str | None = Query(None, max_length=200), status: str | None = None, saved: bool | None = None,
    intent: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(current_user),
) -> dict:
    conds, params = ["user_id = :u"], {"u": user.id, "lim": limit, "off": offset}
    if q:
        conds.append("(question ILIKE :q OR title ILIKE :q)")
        params["q"] = f"%{q.replace('%', '').replace('_', '')}%"
    if status:
        conds.append("status = :st")
        params["st"] = status
    if saved is not None:
        conds.append("saved = :sv")
        params["sv"] = saved
    if intent:
        conds.append("intent = :it")
        params["it"] = intent
    where = " AND ".join(conds)
    with app_tx() as c:
        total = c.execute(text(f"SELECT COUNT(*) FROM app.analyses WHERE {where}"), params).scalar()
        rows = c.execute(
            text(f"SELECT id, question, title, status, mode, intent, saved, created_at, duration_ms, dataset_id, parent_id,"
                 f" explanation -> 'summary' ->> 'text' AS summary, error_message FROM app.analyses WHERE {where}"
                 " ORDER BY created_at DESC, id DESC LIMIT :lim OFFSET :off"), params,
        ).mappings().all()
    return {"items": [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get("/{aid}", response_model=AnalysisOut)
def get_analysis(aid: int, user: CurrentUser = Depends(current_user)) -> AnalysisOut:
    return _out(load_analysis(aid, user))


@router.patch("/{aid}", response_model=AnalysisOut)
def patch_analysis(aid: int, body: AnalysisPatch, user: CurrentUser = Depends(current_user)) -> AnalysisOut:
    load_analysis(aid, user)
    sets, params = [], {"id": aid, "u": user.id}
    if body.saved is not None:
        sets.append("saved = :saved")
        params["saved"] = body.saved
    if body.title is not None:
        sets.append("title = :title")
        params["title"] = body.title.strip()
    if sets:
        with app_tx() as c:
            c.execute(text(f"UPDATE app.analyses SET {', '.join(sets)} WHERE id = :id AND user_id = :u"), params)
    return _out(load_analysis(aid, user))


@router.delete("/{aid}", status_code=204)
def delete_analysis(aid: int, user: CurrentUser = Depends(current_user)) -> Response:
    load_analysis(aid, user)
    with app_tx() as c:
        c.execute(text("DELETE FROM app.analyses WHERE id = :id AND user_id = :u"), {"id": aid, "u": user.id})
    return Response(status_code=204)


@router.post("/{aid}/retry", status_code=201, response_model=AnalysisOut)
def retry_analysis(aid: int, user: CurrentUser = Depends(current_user),
                   provider: LLMProvider | None = Depends(provider_dep)) -> AnalysisOut:
    """Re-run the same question against current data. Creates a new, linked investigation."""
    limiter.check(f"analysis:{user.id}", get_settings().analysis_rate_limit_per_minute)
    old = load_analysis(aid, user)
    ds = dataset_for_user(user, old["dataset_id"])
    new_id = run_analysis(user=user, dataset=ds, question=old["question"], provider=provider, parent_id=aid)
    a = load_analysis(new_id, user)
    a["result_is_historical"] = False
    return _out(a)


@router.get("/{aid}/export")
def export_analysis(aid: int, format: str = Query("markdown", pattern="^(markdown|pdf)$"),
                    user: CurrentUser = Depends(current_user)) -> Response:
    a = load_analysis(aid, user)
    md = analysis_to_markdown(a)
    name = f"ai-workmate-investigation-{aid}"
    if format == "pdf":
        return Response(markdown_to_pdf(md, a.get("title") or a["question"]), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return Response(md, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
