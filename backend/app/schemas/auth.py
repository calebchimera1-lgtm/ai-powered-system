"""Authentication request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255, description="Username or email")
    password: str = Field(..., min_length=1, max_length=128)
    otp: str | None = Field(None, max_length=10, description="6-digit code, if two-step is on")


class RoleBrief(ORMModel):
    id: int
    name: str
    display_name: str


class CurrentUser(ORMModel):
    id: int
    full_name: str
    username: str
    email: str
    phone: str | None
    role: RoleBrief
    permissions: list[str]
    must_change_password: bool
    mfa_enabled: bool = False
    last_login_at: datetime | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    user: CurrentUser


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=200)
    new_password: str = Field(..., min_length=1, max_length=128)


class SessionOut(ORMModel):
    id: int
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    is_current: bool = False


class MfaSetupRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


class MfaSetupResponse(BaseModel):
    """Shown once, to the signed-in user only, so they can add the account to their app."""

    secret: str
    otpauth_uri: str


class MfaCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=10)


class MfaDisableRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=6, max_length=10)
