from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.ingestion import router as ingestion_router
from app.core.errors import validation_error_handler

app = FastAPI(title="finguard-backend", version="0.1.0")

app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(ingestion_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
