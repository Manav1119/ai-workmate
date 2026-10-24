from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy import text

from app.config import get_settings
from app.connectors.base import list_connectors
from app.db import app_tx
from app.errors import ApiError
from app.schemas import ImportIn
from app.security.auth import CurrentUser, current_user, dataset_for_user
from app.security.rate_limit import limiter
from app.services import csv_import
from app.services.datasets import freshness

router = APIRouter(prefix="/api/data-sources", tags=["data-sources"])


def _ds_out(d: dict, user: CurrentUser) -> dict:
    out = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}
    out["is_public"] = d["owner_user_id"] is None
    out["is_active"] = (user.active_dataset_id or 1) == d["id"]
    out["freshness"] = freshness(d, user.reporting_timezone)
    return out


@router.get("")
def list_sources(user: CurrentUser = Depends(current_user)) -> dict:
    with app_tx() as c:
        rows = c.execute(text("SELECT * FROM app.datasets WHERE owner_user_id IS NULL OR owner_user_id = :u ORDER BY id"),
                         {"u": user.id}).mappings().all()
    return {"items": [_ds_out(dict(r), user) for r in rows], "connectors": list_connectors()}


@router.get("/{dataset_id}/preview")
def preview(dataset_id: int, user: CurrentUser = Depends(current_user)) -> dict:
    ds = dataset_for_user(user, dataset_id)
    with app_tx() as c:
        camps = c.execute(text("SELECT campaign_id, campaign_name, platform, objective, start_date, status FROM"
                               " analytics.campaigns WHERE dataset_id = :d ORDER BY campaign_id"), {"d": ds["id"]}
                          ).mappings().all()
        rows = c.execute(text("SELECT date, campaign_id, spend::float spend, impressions, clicks, conversions,"
                              " revenue::float revenue FROM analytics.campaign_daily_metrics WHERE dataset_id = :d"
                              " ORDER BY date DESC, campaign_id LIMIT 20"), {"d": ds["id"]}).mappings().all()
    conv = lambda r: {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}  # noqa: E731
    return {"dataset": _ds_out(ds, user), "campaigns": [conv(r) for r in camps], "recent_rows": [conv(r) for r in rows]}


@router.post("/upload")
async def upload(file: UploadFile = File(...), user: CurrentUser = Depends(current_user)) -> dict:
    limiter.check(f"upload:{user.id}", 10)
    s = get_settings()
    raw = await file.read(s.upload_max_bytes + 1)
    return csv_import.stage_upload(file.filename or "upload.csv", raw)


@router.post("/imports/{upload_id}", status_code=201)
def do_import(upload_id: str, body: ImportIn, user: CurrentUser = Depends(current_user)) -> dict:
    if user.is_demo:
        raise ApiError(403, "demo_readonly",
                       "The shared demo account can validate uploads but not store them. Create an account to import.")
    limiter.check(f"import:{user.id}", 5)
    return csv_import.import_upload(upload_id, body.mapping, body.dataset_name, body.reporting_timezone, user.id)


@router.delete("/{dataset_id}", status_code=204)
def delete_source(dataset_id: int, user: CurrentUser = Depends(current_user)) -> Response:
    ds = dataset_for_user(user, dataset_id)
    if ds["owner_user_id"] != user.id:
        raise ApiError(403, "forbidden", "Only your own uploaded datasets can be deleted.")
    with app_tx() as c:
        c.execute(text("UPDATE app.users SET active_dataset_id = NULL WHERE active_dataset_id = :d"), {"d": ds["id"]})
        c.execute(text("DELETE FROM app.datasets WHERE id = :d AND owner_user_id = :u"), {"d": ds["id"], "u": user.id})
    return Response(status_code=204)
