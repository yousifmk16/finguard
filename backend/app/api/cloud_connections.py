"""Cloud provider connection settings.

GET    /api/v1/settings/connections            — list connection status (admin only)
PUT    /api/v1/settings/connections/aws        — save AWS credentials (admin only)
PUT    /api/v1/settings/connections/gcp        — save GCP credentials (admin only)
DELETE /api/v1/settings/connections/{provider} — remove a connection (admin only)

Credentials are stored in-memory for the process lifetime. In production,
encrypt and persist them to a secrets store (e.g. AWS Secrets Manager / GCP
Secret Manager) rather than keeping plaintext in RAM.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.rbac import require_admin

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# In-memory store keyed by provider — same lifecycle as the thresholds store.
_connections: dict[str, dict[str, str]] = {}


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #

class AWSCredentials(BaseModel):
    access_key_id: str = Field(..., min_length=1)
    secret_access_key: str = Field(..., min_length=1)
    region: str = Field("us-east-1", min_length=1)


class GCPCredentials(BaseModel):
    project_id: str = Field(..., min_length=1)
    service_account_json: str = Field(..., min_length=2)


class ConnectionStatus(BaseModel):
    provider: str
    connected: bool
    region: str | None = None
    project_id: str | None = None
    masked_key: str | None = None


class ConnectionsResponse(BaseModel):
    aws: ConnectionStatus
    gcp: ConnectionStatus


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _mask(key: str) -> str:
    """Return a redacted version of a key suitable for display."""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _aws_status() -> ConnectionStatus:
    aws = _connections.get("aws")
    return ConnectionStatus(
        provider="aws",
        connected=aws is not None,
        region=aws.get("region") if aws else None,
        masked_key=_mask(aws["access_key_id"]) if aws else None,
    )


def _gcp_status() -> ConnectionStatus:
    gcp = _connections.get("gcp")
    return ConnectionStatus(
        provider="gcp",
        connected=gcp is not None,
        project_id=gcp.get("project_id") if gcp else None,
    )


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #

@router.get(
    "/connections",
    response_model=ConnectionsResponse,
    summary="Get cloud connection status",
    dependencies=[Depends(require_admin)],
)
def get_connections() -> ConnectionsResponse:
    return ConnectionsResponse(aws=_aws_status(), gcp=_gcp_status())


@router.put(
    "/connections/aws",
    response_model=ConnectionStatus,
    summary="Save AWS credentials",
    dependencies=[Depends(require_admin)],
)
def put_aws(body: AWSCredentials) -> ConnectionStatus:
    _connections["aws"] = body.model_dump()
    return _aws_status()


@router.put(
    "/connections/gcp",
    response_model=ConnectionStatus,
    summary="Save GCP credentials",
    dependencies=[Depends(require_admin)],
)
def put_gcp(body: GCPCredentials) -> ConnectionStatus:
    _connections["gcp"] = body.model_dump()
    return _gcp_status()


@router.delete(
    "/connections/{provider}",
    response_model=ConnectionStatus,
    summary="Remove a cloud connection",
    dependencies=[Depends(require_admin)],
)
def delete_connection(provider: Literal["aws", "gcp"]) -> ConnectionStatus:
    if provider not in _connections:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{provider} connection not found",
        )
    _connections.pop(provider)
    return ConnectionStatus(provider=provider, connected=False)
