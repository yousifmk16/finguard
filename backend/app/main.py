from fastapi import FastAPI

from app.api.ingestion import router as ingestion_router

app = FastAPI(title="finguard-backend", version="0.1.0")

app.include_router(ingestion_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
