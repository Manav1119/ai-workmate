from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import app_tx
from app.errors import ApiError
from app.schemas import LoginIn, RegisterIn, UserOut, UserSettingsIn
from app.security.auth import (
    COOKIE_NAME, CurrentUser, current_user, dataset_for_user, hash_password, issue_token, load_user, verify_password,
)
from app.security.rate_limit import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _session(resp: Response, user_id: int) -> dict:
    s = get_settings()
    token = issue_token(user_id)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                    max_age=s.jwt_ttl_minutes * 60, path="/")
    u = load_user(user_id)
    return {"user": UserOut(**u.__dict__).model_dump(), "token": token}


def _ip(req: Request) -> str:
    return req.client.host if req.client else "unknown"


@router.post("/login")
def login(body: LoginIn, req: Request, resp: Response) -> dict:
    limiter.check(f"login:{_ip(req)}", 10)
    with app_tx() as c:
        row = c.execute(text("SELECT id, password_hash, is_demo FROM app.users WHERE email = :e"),
                        {"e": body.email}).mappings().first()
    if not row or row["is_demo"] or not verify_password(body.password, row["password_hash"]):
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect.")
    return _session(resp, row["id"])


@router.post("/register", status_code=201)
def register(body: RegisterIn, req: Request, resp: Response) -> dict:
    s = get_settings()
    if not s.allow_registration:
        raise ApiError(403, "registration_disabled", "Registration is disabled on this deployment.")
    limiter.check(f"register:{_ip(req)}", 5)
    with app_tx() as c:
        public = c.execute(text("SELECT id FROM app.datasets WHERE owner_user_id IS NULL ORDER BY id LIMIT 1")).scalar()
        try:
            uid = c.execute(
                text("INSERT INTO app.users (email, display_name, password_hash, reporting_timezone, active_dataset_id)"
                     " VALUES (:e, :n, :h, :tz, :d) RETURNING id"),
                {"e": body.email, "n": body.display_name.strip(), "h": hash_password(body.password),
                 "tz": s.default_reporting_timezone, "d": public},
            ).scalar()
        except IntegrityError as e:
            raise ApiError(409, "email_taken", "An account with this email already exists.") from e
    return _session(resp, uid)


@router.post("/demo")
def demo_login(req: Request, resp: Response) -> dict:
    if not get_settings().allow_demo_login:
        raise ApiError(403, "demo_disabled", "Demo login is disabled on this deployment.")
    limiter.check(f"demo:{_ip(req)}", 30)
    with app_tx() as c:
        uid = c.execute(text("SELECT id FROM app.users WHERE is_demo ORDER BY id LIMIT 1")).scalar()
    if not uid:
        raise ApiError(503, "demo_unavailable", "The demo account has not been seeded. Run the seed script.")
    return _session(resp, uid)


@router.post("/logout")
def logout(resp: Response) -> dict:
    resp.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser = Depends(current_user)) -> UserOut:
    return UserOut(**user.__dict__)


@router.patch("/me", response_model=UserOut)
def update_me(body: UserSettingsIn, user: CurrentUser = Depends(current_user)) -> UserOut:
    sets, params = [], {"id": user.id}
    if body.display_name is not None:
        sets.append("display_name = :dn")
        params["dn"] = body.display_name.strip()
    if body.reporting_timezone is not None:
        try:
            ZoneInfo(body.reporting_timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ApiError(422, "invalid_timezone", f"Unknown timezone '{body.reporting_timezone}'.") from e
        sets.append("reporting_timezone = :tz")
        params["tz"] = body.reporting_timezone
    if body.anomaly_sensitivity is not None:
        sets.append("anomaly_sensitivity = :sens")
        params["sens"] = body.anomaly_sensitivity
    if body.active_dataset_id is not None:
        dataset_for_user(user, body.active_dataset_id)  # authorization check
        sets.append("active_dataset_id = :ds")
        params["ds"] = body.active_dataset_id
    if user.is_demo and (body.display_name is not None):
        raise ApiError(403, "demo_readonly", "The shared demo account's name can't be changed.")
    if sets:
        with app_tx() as c:
            c.execute(text(f"UPDATE app.users SET {', '.join(sets)} WHERE id = :id"), params)
    return UserOut(**load_user(user.id).__dict__)
