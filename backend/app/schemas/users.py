"""User administration schemas."""

import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.auth import RoleBrief
from app.schemas.common import ORMModel

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,50}$")
PHONE_RE = re.compile(r"^\+?[0-9 ]{7,20}$")


def _clean_phone(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not PHONE_RE.match(value):
        raise ValueError("must be a phone number such as +254712345678")
    return value


class UserBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=150)
    email: EmailStr
    phone: str | None = Field(None, max_length=30)

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("is too short")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return _clean_phone(v)


class UserCreate(UserBase):
    username: str = Field(..., min_length=3, max_length=50)
    role: str = Field(..., description="Role name, e.g. cashier")
    password: str | None = Field(
        None,
        max_length=128,
        description="Initial password. If omitted, a one-time setup link is returned instead.",
    )

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("use 3-50 letters, digits, dots, dashes or underscores")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=150)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=30)
    role: str | None = None
    is_active: bool | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return _clean_phone(v)


class UserOut(ORMModel):
    id: int
    full_name: str
    username: str
    email: str
    phone: str | None
    role: RoleBrief
    is_active: bool
    must_change_password: bool
    is_locked: bool = False
    last_login_at: datetime | None
    created_at: datetime


class UserCreated(BaseModel):
    user: UserOut
    setup_url: str | None = None
    setup_expires_at: datetime | None = None


class PasswordResetIssued(BaseModel):
    reset_url: str
    expires_at: datetime


class PermissionOut(ORMModel):
    code: str
    description: str


class RoleOut(ORMModel):
    id: int
    name: str
    display_name: str
    description: str
    permissions: list[PermissionOut]
    user_count: int = 0
