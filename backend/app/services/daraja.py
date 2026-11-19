"""Client for Safaricom's Daraja API: M-Pesa STK push ("Lipa Na M-Pesa Online").

Three calls are used:
- OAuth token: GET /oauth/v1/generate?grant_type=client_credentials (Basic auth)
- STK push:   POST /mpesa/stkpush/v1/processrequest
- STK query:  POST /mpesa/stkpushquery/v1/query

Credentials come only from settings (environment variables) and are never logged or
returned to the browser.
"""

import base64
import logging
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}


class DarajaError(Exception):
    """A failure talking to Safaricom; the message is safe to show to staff."""


class DarajaClient:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings or get_settings()
        self.base = BASE_URLS[self.settings.mpesa_environment]
        self._transport = transport
        self._token: str | None = None
        self._token_expires = 0.0
        self._lock = threading.Lock()

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base, timeout=30.0, transport=self._transport)

    # --- auth ------------------------------------------------------------------------
    def token(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._token_expires:
                return self._token
            s = self.settings
            try:
                with self._client() as c:
                    r = c.get(
                        "/oauth/v1/generate",
                        params={"grant_type": "client_credentials"},
                        auth=(s.mpesa_consumer_key, s.mpesa_consumer_secret),
                    )
            except httpx.HTTPError as exc:
                logger.warning(
                    "M-Pesa: could not reach Safaricom for a token: %s", type(exc).__name__
                )
                raise DarajaError("Could not reach M-Pesa. Check the internet connection.") from exc
            if r.status_code != 200:
                logger.warning("M-Pesa: token request refused (HTTP %s)", r.status_code)
                raise DarajaError(
                    "M-Pesa refused the shop's credentials. Check the Daraja settings."
                )
            data = r.json()
            self._token = data["access_token"]
            # Daraja tokens last an hour; renew a minute early.
            self._token_expires = time.monotonic() + max(60, int(data.get("expires_in", 3599)) - 60)
            return self._token

    # --- helpers ---------------------------------------------------------------------
    def _password(self) -> tuple[str, str]:
        s = self.settings
        ts = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
        raw = f"{s.mpesa_shortcode}{s.mpesa_passkey}{ts}".encode()
        return base64.b64encode(raw).decode(), ts

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._client() as c:
                r = c.post(path, json=body, headers={"Authorization": f"Bearer {self.token()}"})
        except httpx.HTTPError as exc:
            logger.warning("M-Pesa: request to %s failed: %s", path, type(exc).__name__)
            raise DarajaError("Could not reach M-Pesa. Check the internet connection.") from exc
        try:
            data = r.json()
        except ValueError as exc:
            raise DarajaError(
                f"M-Pesa returned an unexpected answer (HTTP {r.status_code})."
            ) from exc
        if r.status_code == 401:
            self._token = None  # expired early: the next call fetches a new one
        return {"_http_status": r.status_code, **data}

    # --- API -------------------------------------------------------------------------
    def stk_push(
        self, *, phone: str, amount: int, reference: str, description: str, callback_url: str
    ) -> dict[str, Any]:
        s = self.settings
        password, ts = self._password()
        buy_goods = s.mpesa_transaction_type == "CustomerBuyGoodsOnline"
        body = {
            "BusinessShortCode": s.mpesa_shortcode,
            "Password": password,
            "Timestamp": ts,
            "TransactionType": s.mpesa_transaction_type,
            "Amount": amount,
            "PartyA": phone,
            "PartyB": (s.mpesa_till_number or s.mpesa_shortcode)
            if buy_goods
            else s.mpesa_shortcode,
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": reference,
            "TransactionDesc": description,
        }
        return self._post("/mpesa/stkpush/v1/processrequest", body)

    def stk_query(self, checkout_request_id: str) -> dict[str, Any]:
        s = self.settings
        password, ts = self._password()
        body = {
            "BusinessShortCode": s.mpesa_shortcode,
            "Password": password,
            "Timestamp": ts,
            "CheckoutRequestID": checkout_request_id,
        }
        return self._post("/mpesa/stkpushquery/v1/query", body)


_client: DarajaClient | None = None


def get_client() -> DarajaClient:
    """One shared client per process, so the OAuth token is reused."""
    global _client
    if _client is None:
        _client = DarajaClient()
    return _client


def set_client(client: DarajaClient | None) -> None:
    """Used by tests to plug in a client with a recorded-response transport."""
    global _client
    _client = client
