"""
FastAPI Main Application.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.nacha import router as nacha_router
from app.api.v1.payments import router as payments_router
from app.api.v1.remittances import router as remittances_router
from app.api.v1.vendors import router as vendors_router
from app.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)


@app.on_event("startup")
async def on_startup():
    """Auto-migrate production database columns on backend startup."""
    from sqlalchemy import text
    from app.db.session import async_engine
    try:
        async with async_engine.begin() as conn:
            await conn.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS invoice_breakdown JSONB;"))
            await conn.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS trace_number VARCHAR(30);"))
            await conn.execute(text("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS email VARCHAR(255);"))
            await conn.execute(text("ALTER TABLE vendor_remittances ADD COLUMN IF NOT EXISTS body_html TEXT;"))
            await conn.execute(text("ALTER TABLE vendor_remittances ADD COLUMN IF NOT EXISTS trace_number VARCHAR(30);"))
    except Exception as err:
        print(f"Startup DB migration warning: {err}")


# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://amipi-nacha.netlify.app",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.middleware("http")
async def add_cors_headers(request, call_next):
    """Ensure CORS headers are present on all responses including 404/500 errors and OPTIONS preflight."""
    if request.method == "OPTIONS":
        from fastapi.responses import Response
        res = Response(status_code=200)
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD, *"
        res.headers["Access-Control-Allow-Headers"] = "*"
        return res

    try:
        response = await call_next(request)
    except Exception as exc:
        from fastapi.responses import JSONResponse
        response = JSONResponse(
            status_code=500,
            content={"detail": str(exc) or "Internal server error"}
        )

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD, *"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response




# Include API v1 Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(payments_router, prefix=settings.API_V1_STR)
app.include_router(vendors_router, prefix=settings.API_V1_STR)
app.include_router(nacha_router, prefix=settings.API_V1_STR)
app.include_router(remittances_router, prefix=settings.API_V1_STR)
app.include_router(audit_router, prefix=settings.API_V1_STR)



@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


@app.get(f"{settings.API_V1_STR}/status", tags=["Status"])
async def status_check():
    """API v1 status endpoint."""
    return {"status": "ok", "api_version": "v1"}


# Serve Frontend static files (must be AFTER API routes)
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/frontend", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend_alias")
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
