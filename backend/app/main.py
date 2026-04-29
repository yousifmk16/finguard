from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.alerts import router as alerts_router
from app.api.anomalies import router as anomalies_router
from app.api.detection import router as detection_router
from app.api.ingestion import router as ingestion_router
from app.api.kpi import router as kpi_router
from app.core.errors import validation_error_handler

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
        "name": "detection",
        "description": "Health and metrics endpoints for the real-time detection pipeline (DET-03).",
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

app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(ingestion_router)
app.include_router(anomalies_router)
app.include_router(alerts_router)
app.include_router(kpi_router)
app.include_router(detection_router)


@app.get("/health", tags=["detection"])
def health() -> dict[str, str]:
    return {"status": "ok"}
