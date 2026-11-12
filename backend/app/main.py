"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.services.rbac_service import sync_roles_and_permissions

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    with SessionLocal() as db:
        sync_roles_and_permissions(db)
        superuser = db.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar()
    if superuser and settings.is_production:
        logger.warning(
            "The API is connected to PostgreSQL as a SUPERUSER. Give it its own role: set "
            "APP_DB_USER and APP_DB_PASSWORD in .env and run `make db-least-privilege`."
        )
    if settings.is_production and not settings.cookie_secure:
        logger.info(
            "COOKIE_SECURE is false: sign-in cookies are Secure only on HTTPS requests. "
            "Serve the site over HTTPS (and set COOKIE_SECURE=true) outside a closed shop LAN."
        )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        description=(
            "REST API for the AI-Driven Smart Inventory Management and Automated Receipt "
            "Digitization System. Amounts are in Kenyan Shillings (KES)."
        ),
        lifespan=lifespan,
        # The schema lists every endpoint and field: not published in production.
        docs_url="/api/docs" if settings.api_docs_enabled else None,
        redoc_url="/api/redoc" if settings.api_docs_enabled else None,
        openapi_url="/api/openapi.json" if settings.api_docs_enabled else None,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.path.startswith("/api/v1"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/api/health", tags=["System"])
    def health() -> dict[str, str]:
        """Liveness/readiness probe used by Docker."""
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    return app


app = create_app()
