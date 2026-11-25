"""
DiaDoc AI — Application Factory
===============================
Enterprise FastAPI application entrypoint. Configures middleware, rate limiting,
static file mounts, and integrates domain route controllers under /api/v1.
"""

import os
import platform
import sys

# Prevent Windows Python 3.12 multiprocessing WMI COM query hang on SQLAlchemy/platform import
if sys.platform == "win32":
    try:
        platform.win32_ver = lambda release="", version="", csd="", ptype="": (
            "10", "10.0.19041", "", "Multiprocessor Free"
        )
    except Exception:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.database import engine, Base
from app.core.limiter import limiter
from app.core.logger import get_logger

log = get_logger(__name__)

# Initialize database tables on startup (idempotent). create_all only creates missing
# tables (all models are registered by importing api_router above); additive column
# changes to pre-existing tables are applied by app.core.database.run_migrations().
Base.metadata.create_all(bind=engine)

# Construct FastAPI instance
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Multimodal Clinical & Scientific Research Intelligence Platform.",
    version="2.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    debug=settings.DEBUG,
)

# Attach rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware (Swagger / local web tooling; the Flutter app is native and needs none)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount rendered PDF page image storage
os.makedirs(settings.RENDERED_PAGES_DIR, exist_ok=True)
app.mount(
    "/rendered_pages",
    StaticFiles(directory=settings.RENDERED_PAGES_DIR),
    name="rendered_pages",
)

# Register API v1 modular routes
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", summary="Root Health Probe", tags=["System"])
def root():
    """Returns basic service health status and API documentation entrypoints."""
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "version": "2.0.0",
        "docs": "/docs",
        "openapi": f"{settings.API_V1_STR}/openapi.json",
        "stream_endpoint": f"{settings.API_V1_STR}/chat/stream",
    }


@app.on_event("startup")
async def on_startup():
    """Validates runtime configuration on boot and logs telemetry."""
    if not settings.GEMINI_API_KEY:
        log.warning(
            "GEMINI_API_KEY is not set in .env — "
            "Gemini endpoints will require an API key to function."
        )
    else:
        log.info("Gemini API key loaded successfully.")

    log.info("Active LLM provider: %s", settings.LLM_PROVIDER)
    log.info("Static pages dir: %s", settings.RENDERED_PAGES_DIR)
    log.info("Index store: %s", settings.INDEX_STORE_PATH)
    log.info("Service initialized (debug=%s)", settings.DEBUG)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
