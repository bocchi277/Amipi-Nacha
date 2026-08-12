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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.middleware("http")
async def add_cors_headers(request, call_next):
    """Ensure CORS headers are present on all responses including 404/500 errors."""
    try:
        response = await call_next(request)
    except Exception as exc:
        from fastapi.responses import JSONResponse
        response = JSONResponse(
            status_code=500,
            content={"detail": str(exc) or "Internal server error"}
        )

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
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
