"""
ECO-IOT-GW Backend - FastAPI Entry Point
IoT Gateway Management API
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .api import auth, docker, terminal, vpn, modem, serial, wifi, system, diagnostics, watchdog, audit, thingsboard, ntp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"{settings.LOG_DIR}/backend.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Initialize services
    try:
        from .services.audit_service import audit_service
        audit_service.initialize()
        logger.info("Audit service initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize audit service: {e}")

    try:
        from .services.watchdog_service import watchdog_service
        watchdog_service.start()
        logger.info("Watchdog service started")
    except Exception as e:
        logger.warning(f"Failed to start watchdog service: {e}")

    yield

    # Shutdown
    logger.info("Shutting down...")

    try:
        from .services.watchdog_service import watchdog_service
        watchdog_service.stop()
    except Exception:
        pass


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="IoT Gateway Management API for Raspberry Pi",
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests."""
    start_time = datetime.now()

    # Get client IP
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    response = await call_next(request)

    # Calculate duration
    duration = (datetime.now() - start_time).total_seconds() * 1000

    # Log request (skip health checks)
    if not request.url.path.endswith("/health"):
        logger.info(
            f"{client_ip} - {request.method} {request.url.path} - "
            f"{response.status_code} - {duration:.2f}ms"
        )

    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else None
        }
    )


# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(docker.router, prefix="/api/docker", tags=["Docker"])
app.include_router(terminal.router, prefix="/api/terminal", tags=["Terminal"])
app.include_router(vpn.router, prefix="/api/vpn", tags=["VPN"])
app.include_router(modem.router, prefix="/api/modem", tags=["Modem"])
app.include_router(serial.router, prefix="/api/serial", tags=["Serial"])
app.include_router(wifi.router, prefix="/api/wifi", tags=["WiFi"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(diagnostics.router, prefix="/api/diagnostics", tags=["Diagnostics"])
app.include_router(watchdog.router, prefix="/api/watchdog", tags=["Watchdog"])
app.include_router(audit.router, prefix="/api/audit", tags=["Audit"])
app.include_router(thingsboard.router, prefix="/api/thingsboard", tags=["ThingsBoard"])
app.include_router(ntp.router, prefix="/api/ntp", tags=["NTP"])


# Health check endpoint
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "timestamp": datetime.now().isoformat()
    }


# Root redirect
@app.get("/api")
async def api_root():
    """API root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs" if settings.DEBUG else None
    }
