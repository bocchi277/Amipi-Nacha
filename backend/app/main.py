import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.nacha import router as nacha_router
from app.api.v1.payments import router as payments_router
from app.api.v1.remittances import router as remittances_router
from app.api.v1.users import router as users_router
from app.api.v1.vendors import router as vendors_router
from app.config import settings
from app.core.request_context import resolve_client_ip, set_client_ip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan.

    This previously ran ad-hoc `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements
    on every boot, which meant Alembic was not actually the source of truth for the
    schema. Those columns now live in migration e7a89b01c2d3; run
    `alembic upgrade head` on deploy. We only verify connectivity here and warn about
    insecure default secrets.
    """
    from sqlalchemy import text
    from app.db.session import async_engine

    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connectivity verified.")
    except Exception:
        logger.exception("Database connectivity check FAILED at startup")

    if settings.SECRET_KEY == "DEVELOPMENT_SECRET_KEY_CHANGE_IN_PROD_123456789":
        logger.warning(
            "SECRET_KEY is the built-in development default. Set the SECRET_KEY "
            "environment variable: JWTs signed with a public default can be forged."
        )

    import os
    if not os.getenv("BANK_DETAILS_ENCRYPTION_KEY"):
        logger.warning(
            "BANK_DETAILS_ENCRYPTION_KEY is not set, so vendor bank details are "
            "encrypted with the default key committed to source control. Set this "
            "variable. NOTE: changing it makes EXISTING encrypted rows unreadable, "
            "so rotate it with a re-encryption migration, not in place."
        )

    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# The previous configuration listed specific origins AND "*", then a middleware
# unconditionally re-set `Access-Control-Allow-Origin: *` on every response, so the
# allowlist was decorative. Any website could call this API from a victim's browser.
#
# Origins are now a real allowlist, overridable via the ALLOWED_ORIGINS env var
# (comma-separated) so deployments can add hosts without a code change.
_DEFAULT_ALLOWED_ORIGINS = [
    "https://amipi-nacha.netlify.app",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8099",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8099",
]


def _resolve_allowed_origins() -> list[str]:
    configured = (settings.ALLOWED_ORIGINS or "").strip()
    if configured and configured != "*":
        return [o.strip() for o in configured.split(",") if o.strip()]
    return list(_DEFAULT_ALLOWED_ORIGINS)


ALLOWED_ORIGINS = _resolve_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """
    Attach defensive response headers and keep internal errors opaque.

    Replaces a middleware that (a) forced `Access-Control-Allow-Origin: *` onto every
    response, defeating the allowlist above, and (b) returned `str(exc)` to the
    client on any unhandled exception, leaking schema details and internal state.
    """
    # Make the caller's IP available to audit logging for this request.
    set_client_ip(resolve_client_ip(request))

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error handling %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred."},
        )

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # CSP allows exactly the third-party origins the dashboard actually needs:
    #   cdn.sheetjs.com     - XLSX library used for the Excel export/template features
    #   fonts.googleapis.com / fonts.gstatic.com - webfonts
    # A stricter policy was verified to BREAK the app: it blocked the SheetJS script
    # (disabling Excel export) and the font stylesheets. 'unsafe-inline' is still
    # required because the dashboard uses inline handlers and styles; frame-ancestors
    # and object-src continue to remove the clickjacking and plugin vectors.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline' https://cdn.sheetjs.com; "
        "connect-src 'self' https://amipi-nacha-backend.onrender.com; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    )
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response




# Include API v1 Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(users_router, prefix=settings.API_V1_STR)
app.include_router(payments_router, prefix=settings.API_V1_STR)
app.include_router(vendors_router, prefix=settings.API_V1_STR)
app.include_router(nacha_router, prefix=settings.API_V1_STR)
app.include_router(remittances_router, prefix=settings.API_V1_STR)
app.include_router(audit_router, prefix=settings.API_V1_STR)



@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.

    Reports database reachability as well as process liveness: previously this
    returned "healthy" even when the database was completely unreachable, so an
    uptime monitor could not distinguish a working deployment from a broken one.
    """
    from sqlalchemy import text
    from app.db.session import async_engine

    db_ok = True
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: database unreachable")
        db_ok = False

    payload = {
        "status": "healthy" if db_ok else "degraded",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "database": "connected" if db_ok else "unreachable",
    }
    return JSONResponse(status_code=200 if db_ok else 503, content=payload)


@app.get(f"{settings.API_V1_STR}/status", tags=["Status"])
async def status_check():
    """API v1 status endpoint."""
    return {"status": "ok", "api_version": "v1"}


# Serve Frontend static files (must be AFTER API routes)
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/frontend", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend_alias")
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
