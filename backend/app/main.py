"""AI Workmate API."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import install_error_handlers
from app.logging_setup import configure_logging, request_id_var
from app.routers import analyses, anomalies, auth, data_sources, meta, reports

log = logging.getLogger("workmate.http")
MAX_JSON_BYTES = 64 * 1024


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging()
    app = FastAPI(
        title="AI Workmate API",
        version="1.0.0",
        description="Natural-language analytics with a validated, read-only text-to-SQL pipeline.",
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["content-type", "x-requested-with", "authorization"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id")
        rid = rid if rid and len(rid) <= 64 and rid.replace("-", "").isalnum() else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            cl = request.headers.get("content-length")
            limit = s.upload_max_bytes + 64 * 1024 if request.url.path.endswith("/upload") else MAX_JSON_BYTES
            if cl and cl.isdigit() and int(cl) > limit:
                return JSONResponse(status_code=413, content={"error": {
                    "code": "payload_too_large", "message": "Request body is too large.", "request_id": rid}})
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            log.info("request", extra={"path": request.url.path, "method": request.method,
                                       "status": response.status_code,
                                       "duration_ms": int((time.perf_counter() - start) * 1000),
                                       "user_id": getattr(request.state, "user_id", None)})
            return response
        finally:
            request_id_var.reset(token)

    for r in (meta.router, auth.router, analyses.router, anomalies.router, reports.router, data_sources.router):
        app.include_router(r)
    return app


app = create_app()
