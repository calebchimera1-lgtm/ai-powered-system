"""Application configuration.

All settings come from environment variables (or a `.env` file in development).
Secrets such as the database password and JWT signing key are never hard-coded.
"""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General ---------------------------------------------------------
    app_name: str = "Smart Inventory"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    store_timezone: str = "Africa/Nairobi"
    currency: str = "KES"

    # --- Database --------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://inventory:inventory@localhost:5432/inventory",
        description="SQLAlchemy URL. Use the postgresql+psycopg:// driver.",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- Security --------------------------------------------------------
    jwt_secret: str = Field(default="change-me-in-env", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    refresh_reuse_grace_seconds: int = 10
    # Always true when a request arrives over HTTPS; set true to force it everywhere.
    cookie_secure: bool = False
    # Interactive API docs (/api/docs, /api/redoc, /api/openapi.json). Off in production.
    expose_api_docs: bool | None = None
    password_min_length: int = 8
    login_max_failures: int = 5
    lockout_minutes: int = 15
    login_rate_limit_per_minute: int = 20  # per client IP
    password_reset_minutes: int = 30

    # --- URLs / CORS -----------------------------------------------------
    frontend_url: str = "http://localhost:8080"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Storage ---------------------------------------------------------
    storage_dir: Path = Path("./storage")
    max_image_mb: int = 5

    # --- Inventory rules ---------------------------------------------------
    # Manual adjustments worth more than this (KES, at cost) need a manager's approval.
    stock_adjustment_approval_threshold: Decimal = Decimal("5000")
    expiry_warning_days: int = 14
    default_vat_rate: Decimal = Decimal("16")
    # Cashiers may discount a sale by up to this percentage without a manager.
    max_cashier_discount_percent: Decimal = Decimal("10")
    # Supplier price changes larger than this are flagged on goods received.
    price_change_alert_percent: Decimal = Decimal("10")

    # --- Store details (printed on receipts) -----------------------------------
    store_name: str = "Smart Supermarket"
    store_address: str = "Nairobi, Kenya"
    store_phone: str = ""
    store_kra_pin: str = ""
    receipt_footer: str = "Thank you for shopping with us!"

    # --- M-Pesa STK push (Safaricom Daraja "Lipa Na M-Pesa Online") ---------
    # The till can send a payment prompt to the customer's phone. Off unless the four
    # credentials below are set (from the Daraja portal: developer.safaricom.co.ke).
    mpesa_environment: Literal["sandbox", "production"] = "sandbox"
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = ""  # Business shortcode (paybill, or the store number for a till)
    mpesa_passkey: str = ""
    # CustomerPayBillOnline for a paybill; CustomerBuyGoodsOnline for a till (Buy Goods).
    mpesa_transaction_type: Literal["CustomerPayBillOnline", "CustomerBuyGoodsOnline"] = (
        "CustomerPayBillOnline"
    )
    mpesa_till_number: str = ""  # Buy Goods only: the till number money goes to (PartyB)
    # Optional: public HTTPS address Safaricom can reach, plus a secret path token, for
    # instant results by callback. Without them the app asks Safaricom for the result.
    mpesa_callback_base_url: str = ""
    mpesa_callback_token: str = ""

    # --- Document archive, optional --------------------------
    # Approved supplier invoices are filed in the document archive automatically: OCR'd, tagged by
    # supplier, searchable. paperless_url is how the server reaches it (inside Docker:
    # http://archive:8000); paperless_public_url is the address staff open in the browser.
    paperless_url: str = ""
    paperless_token: str = ""
    paperless_public_url: str = ""

    # --- AI assistant and AI invoice reading (Claude API), optional -----------
    # With an API key from console.anthropic.com the app gets an accounting assistant that
    # answers questions from the shop's own records and reads receipt/invoice photos.
    # The key stays on the server; the browser never sees it. Empty = feature off.
    anthropic_api_key: str = ""
    assistant_model: str = "claude-opus-5-5"
    assistant_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Read scanned supplier invoices with Claude vision (falls back to Tesseract on errors).
    ai_invoice_reading: bool = True

    # --- Worker ----------------------------------------------------------
    worker_poll_seconds: float = 2.0
    worker_max_attempts: int = 3
    # If no worker has checked in for a minute, the API reads uploaded invoices itself so
    # scanning still works (for example when only the API was started from an editor).
    worker_inline_fallback: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def mpesa_enabled(self) -> bool:
        return all(
            (
                self.mpesa_consumer_key,
                self.mpesa_consumer_secret,
                self.mpesa_shortcode,
                self.mpesa_passkey,
            )
        )

    @property
    def archive_enabled(self) -> bool:
        return bool(self.paperless_url and self.paperless_token)

    @property
    def assistant_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def ai_invoice_reader_enabled(self) -> bool:
        return self.assistant_enabled and self.ai_invoice_reading

    @property
    def api_docs_enabled(self) -> bool:
        return self.expose_api_docs if self.expose_api_docs is not None else not self.is_production


# Values that mean "nobody configured this": the code default and the .env.example placeholders.
_PLACEHOLDERS = ("change-me", "change_me", "changeme")
_DEFAULT_DB_PASSWORDS = {"inventory", "postgres", "password"}


def production_config_problems(settings: Settings) -> list[str]:
    """Reasons the configuration is unsafe for production (never includes secret values)."""
    problems = []
    secret = settings.jwt_secret
    if any(p in secret.lower() for p in _PLACEHOLDERS) or len(secret) < 32:
        problems.append(
            "JWT_SECRET must be a random value of at least 32 characters "
            '(python3 -c "import secrets; print(secrets.token_urlsafe(48))")'
        )
    db_password = make_url(settings.database_url).password or ""
    if (
        any(p in db_password.lower() for p in _PLACEHOLDERS)
        or db_password.lower() in _DEFAULT_DB_PASSWORDS
        or len(db_password) < 12
    ):
        problems.append("POSTGRES_PASSWORD must be changed to a random value of 12+ characters")
    if settings.mpesa_callback_base_url:
        if not settings.mpesa_callback_base_url.startswith("https://"):
            problems.append("MPESA_CALLBACK_BASE_URL must start with https://")
        if len(settings.mpesa_callback_token) < 24:
            problems.append("MPESA_CALLBACK_TOKEN must be a random value of at least 24 characters")
    return problems


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        problems = production_config_problems(settings)
        if problems:
            # Fail closed: refuse to start rather than run with guessable secrets.
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
    return settings
