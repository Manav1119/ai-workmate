"""Consistent error format: {"error": {"code", "message", "request_id", "details?"}}."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_setup import request_id_var

log = logging.getLogger("workmate.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | list | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def _body(code: str, message: str, details=None) -> dict:
    err = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details is not None:
        err["details"] = details
    return {"error": err}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        headers = {"Retry-After": "60"} if exc.status == 429 else None
        return JSONResponse(status_code=exc.status, content=_body(exc.code, exc.message, exc.details), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg", "")} for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_body("invalid_request", "Request validation failed.", details))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content=_body("internal_error", "Something went wrong on our side. The error has been logged."),
        )
