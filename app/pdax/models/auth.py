"""
PDAX authentication models.

POST /login returns either a full token set (no MFA) or an MFA challenge.
POST /login/otp and PUT /refresh-token both return a `TokenSet`. Access and
id tokens live 10 minutes; the refresh token lives 30 days.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., description="PDAX account email")
    password: str


class OtpRequest(BaseModel):
    session: str = Field(..., description="MFA session token from /login")
    username: str
    otp: str = Field(..., description="One-time password code")


class RefreshRequest(BaseModel):
    username: str
    refresh_token: str = Field(..., alias="refreshToken")

    model_config = {"populate_by_name": True}


class TokenSet(BaseModel):
    """Full token bundle returned on successful (non-challenge) auth."""

    email: str
    username: str = Field(..., description="PDAX account UUID")
    groups: list[str] = Field(default_factory=list)
    token_type: str = "Bearer"
    preferred_mfa: str = "NOT_SET"
    expiry: int = 600
    access_token: str
    id_token: str
    refresh_token: str


class MfaChallenge(BaseModel):
    """Returned by /login when MFA is enabled — call /login/otp next."""

    code: str
    message: str
    challenge_name: str
    session: str
