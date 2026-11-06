"""Supplier schemas."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel

KRA_PIN_RE = re.compile(r"^[AP]\d{9}[A-Z]$")
PHONE_RE = re.compile(r"^\+?[0-9 ]{7,20}$")


def _pin(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip().upper()
    if not KRA_PIN_RE.match(v):
        raise ValueError("a KRA PIN looks like P051234567X (letter, 9 digits, letter)")
    return v


def _phone(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip()
    if not PHONE_RE.match(v):
        raise ValueError("must be a phone number such as +254712345678")
    return v


class SupplierIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    kra_pin: str | None = None
    contact_person: str | None = Field(None, max_length=150)
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)
    payment_terms_days: int = Field(30, ge=0, le=365)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("kra_pin")
    @classmethod
    def _kra(cls, v: str | None) -> str | None:
        return _pin(v)

    @field_validator("phone")
    @classmethod
    def _ph(cls, v: str | None) -> str | None:
        return _phone(v)


class SupplierUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=150)
    kra_pin: str | None = None
    contact_person: str | None = Field(None, max_length=150)
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    notes: str | None = Field(None, max_length=2000)
    is_active: bool | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("kra_pin")
    @classmethod
    def _kra(cls, v: str | None) -> str | None:
        return _pin(v)

    @field_validator("phone")
    @classmethod
    def _ph(cls, v: str | None) -> str | None:
        return _phone(v)


class SupplierOut(ORMModel):
    id: int
    name: str
    kra_pin: str | None
    contact_person: str | None
    phone: str | None
    email: str | None
    address: str | None
    payment_terms_days: int
    notes: str | None
    is_active: bool
    product_count: int = 0
    created_at: datetime


class SupplierProductIn(BaseModel):
    supplier_sku: str | None = Field(None, max_length=50)
    last_unit_price: Annotated[Decimal, Field(ge=0, decimal_places=2)] | None = None
    lead_time_days: int | None = Field(None, ge=0, le=365)


class SupplierProductOut(BaseModel):
    supplier_id: int
    supplier_name: str
    product_id: int
    product_name: str
    product_sku: str
    supplier_sku: str | None
    last_unit_price: Decimal | None
    lead_time_days: int | None
    updated_at: datetime
