"""SEC-01: Pydantic schemas for the auth endpoints."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "analyst"]


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Registered user email")
    password: str = Field(..., min_length=1, description="Plaintext password")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="Signed JWT bearer token")
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., description="Token lifetime in seconds")
    role: Role = Field(..., description="Role granted to the authenticated user")


class CurrentUser(BaseModel):
    """Resolved identity attached to a request via ``get_current_user``."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    email: EmailStr
    role: Role
