"""Authentication: bcrypt password hashes + signed JWT session.

The browser receives the JWT in an httpOnly, SameSite=Lax cookie (never readable by JS).
API clients and tests may use ``Authorization: Bearer <token>`` instead.

CSRF: cookie-authenticated state-changing requests must carry the custom header
``X-Requested-With: aiworkmate`` (a cross-site form or image cannot set it).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import bcrypt
import jwt
from fastapi import Depends, Request
from sqlalchemy import text

from app.config import get_settings
from app.db import app_tx
from app.errors import ApiError

COOKIE_NAME = "aw_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "aiworkmate"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class CurrentUser:
    id: int
    email: str
    display_name: str
    is_demo: bool
    reporting_timezone: str
    anomaly_sensitivity: str
    active_dataset_id: int | None


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def issue_token(user_id: int) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + dt.timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_token(token: str) -> int:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise ApiError(401, "unauthenticated", "Your session is invalid or has expired. Please sign in.") from e


def load_user(user_id: int) -> CurrentUser | None:
    with app_tx() as c:
        r = c.execute(
            text(
                "SELECT id, email, display_name, is_demo, reporting_timezone, anomaly_sensitivity, active_dataset_id"
                " FROM app.users WHERE id = :id"
            ),
            {"id": user_id},
        ).mappings().first()
    return CurrentUser(**r) if r else None


def current_user(request: Request) -> CurrentUser:
    token = None
    via_cookie = False
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif request.cookies.get(COOKIE_NAME):
        token = request.cookies[COOKIE_NAME]
        via_cookie = True
    if not token:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    if via_cookie and request.method not in SAFE_METHODS:
        if request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE:
            raise ApiError(403, "csrf_check_failed", "Missing anti-CSRF header.")
    user = load_user(decode_token(token))
    if not user:
        raise ApiError(401, "unauthenticated", "Account not found. Please sign in again.")
    request.state.user_id = user.id
    return user


CurrentUserDep = Depends(current_user)


def dataset_for_user(user: CurrentUser, dataset_id: int | None) -> dict:
    """Authorization: a user may read public datasets and their own uploads only."""
    did = dataset_id or user.active_dataset_id
    with app_tx() as c:
        if did is None:
            row = c.execute(
                text("SELECT * FROM app.datasets WHERE owner_user_id IS NULL ORDER BY id LIMIT 1")
            ).mappings().first()
        else:
            row = c.execute(text("SELECT * FROM app.datasets WHERE id = :id"), {"id": did}).mappings().first()
    if not row:
        raise ApiError(404, "dataset_not_found", "Dataset not found.")
    if row["owner_user_id"] is not None and row["owner_user_id"] != user.id:
        # do not reveal existence of other users' datasets
        raise ApiError(404, "dataset_not_found", "Dataset not found.")
    return dict(row)
