import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.alerts import router as alerts_router
from app.api.cloud_connections import router as cloud_connections_router
from app.api.datagen import router as datagen_router
from app.api.training import router as training_router
from app.api.settings import router as settings_router
from app.api.users import router as users_router
from app.api.anomalies import router as anomalies_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.detection import router as detection_router
from app.api.health import router as health_router
from app.api.ingestion import router as ingestion_router
from app.api.kpi import router as kpi_router
from app.api.metrics import router as metrics_router
from app.core.errors import validation_error_handler
from app.core.logging_config import configure_logging
from app.core.metrics_middleware import MetricsMiddleware
from app.core.middleware import RequestIdMiddleware

# OPS-02: install structured logging before any module-level loggers fire.
configure_logging()

# API-06: tag descriptions shown in /docs
_TAGS = [
    {
        "name": "ingestion",
        "description": "Ingest raw billing events from cloud providers (ING-01/02/03).",
    },
    {
        "name": "anomalies",
        "description": (
            "Query, inspect, and triage detected billing anomalies. "
            "Supports pagination, filtering, detail retrieval, and status transitions "
            "(open → acknowledged → resolved / suppressed)."
        ),
    },
    {
        "name": "alerts",
        "description": "Query alert delivery records produced by the alert orchestration service (ALT-01).",
    },
    {
        "name": "kpi",
        "description": "Aggregated KPI statistics for the dashboard (API-05).",
    },
    {
        "name": "health",
        "description": "Aggregate service health check (OPS-01). Used by load balancers and container orchestrators.",
    },
    {
        "name": "detection",
        "description": "Health and metrics endpoints for the real-time detection pipeline (DET-03).",
    },
    {
        "name": "auth",
        "description": "JWT authentication: login and bearer-token issuance (SEC-01).",
    },
    {
        "name": "audit",
        "description": "Admin-only audit log retrieval for auth and privileged actions (SEC-04).",
    },
]

app = FastAPI(
    title="FinGuard API",
    version="0.1.0",
    description=(
        "Real-time cloud billing anomaly detection platform.\n\n"
        "FinGuard ingests billing events from GCP, AWS, and Azure, scores them with "
        "a weighted ensemble of time-series forecasting, Isolation Forest, and deterministic "
        "rules, and surfaces anomalies through a queryable REST API with lifecycle management."
    ),
    contact={"name": "FinGuard Team", "email": "yousif.alshammrei@gmail.com"},
    openapi_tags=_TAGS,
    docs_url="/docs",
    redoc_url="/redoc",
)

# INT-01: Allow the deployed frontend to call the API cross-origin.
# Origins are read from FINGUARD_CORS_ORIGINS as a comma-separated list, e.g.
#     FINGUARD_CORS_ORIGINS="https://app.finguard.io,https://staging.finguard.io"
# Defaults cover Vite dev (port 3000) and the alternate localhost form so the
# zero-config local workflow keeps working out of the box.
_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [
    origin.strip()
    for origin in os.getenv("FINGUARD_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    # The bearer token in Authorization is the only auth header the UI sends,
    # but methods cover the PATCH used by anomaly status updates (API-03).
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    # OPS-02: clients can read the request id off the response for support tickets.
    expose_headers=["X-Request-ID"],
)
# OPS-02: stamp every request/response with a trace id and bind it to logs.
app.add_middleware(RequestIdMiddleware)
# OPS-03: record HTTP request metrics for /metrics scraping. Added last so
# it sits outermost — it observes every request that reaches the app.
app.add_middleware(MetricsMiddleware)

app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(auth_router)
app.include_router(ingestion_router)
app.include_router(anomalies_router)
app.include_router(alerts_router)
app.include_router(kpi_router)
app.include_router(detection_router)
app.include_router(audit_router)
app.include_router(users_router)
app.include_router(datagen_router)
app.include_router(training_router)
app.include_router(settings_router)
app.include_router(cloud_connections_router)
