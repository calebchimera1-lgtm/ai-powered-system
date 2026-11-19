# ruff: noqa: F811  (the shop fixture is imported from the sales tests)
"""M-Pesa STK push: prompt, result by query or callback, and paying a sale with it.

Safaricom is replaced by a fake Daraja server (httpx.MockTransport) that answers with the
documented Daraja response formats and checks what the app sends. A live call against the
Daraja sandbox needs the shop's own credentials and is done by hand (see the install guide).
"""

import base64
import json
import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings, production_config_problems
from app.core.exceptions import ValidationFailed
from app.services import daraja, mpesa_service
from tests.integration.test_sales_api import shop  # noqa: F401  (fixture)

PUSH = "/api/v1/payments/mpesa/stk-push"
TOKEN = "cb-token-0123456789abcdefghijk"
PASSKEY = "test-passkey-not-a-real-one"


class FakeDaraja:
    """Behaves like the Daraja API for STK push and STK query."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.results: dict[str, tuple[str, str] | None] = {}
        self.reject_push: dict | None = None
        self.down = False
        self.n = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("no route to host")
        path = request.url.path
        if path == "/oauth/v1/generate":
            auth = base64.b64decode(request.headers["Authorization"].split()[1]).decode()
            assert auth == "key:secret"
            return httpx.Response(200, json={"access_token": "tok123", "expires_in": "3599"})
        assert request.headers["Authorization"] == "Bearer tok123"
        body = json.loads(request.content)
        self.requests.append((path, body))
        if path == "/mpesa/stkpush/v1/processrequest":
            if self.reject_push:
                return httpx.Response(400, json=self.reject_push)
            self.n += 1
            cid = f"ws_CO_19112026{self.n:010d}"
            self.results[cid] = None
            return httpx.Response(
                200,
                json={
                    "MerchantRequestID": f"29115-{self.n}",
                    "CheckoutRequestID": cid,
                    "ResponseCode": "0",
                    "ResponseDescription": "Success. Request accepted for processing",
                    "CustomerMessage": "Success. Request accepted for processing",
                },
            )
        if path == "/mpesa/stkpushquery/v1/query":
            res = self.results.get(body["CheckoutRequestID"])
            if res is None:
                return httpx.Response(
                    500,
                    json={
                        "requestId": "1",
                        "errorCode": "500.001.1001",
                        "errorMessage": "The transaction is being processed",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "ResponseCode": "0",
                    "ResponseDescription": "The service request has been accepted successsfully",
                    "MerchantRequestID": "x",
                    "CheckoutRequestID": body["CheckoutRequestID"],
                    "ResultCode": res[0],
                    "ResultDesc": res[1],
                },
            )
        return httpx.Response(404, json={})


@pytest.fixture
def mpesa(monkeypatch):  # type: ignore[no-untyped-def]
    s = get_settings()
    for k, v in {
        "mpesa_consumer_key": "key",
        "mpesa_consumer_secret": "secret",
        "mpesa_shortcode": "174379",
        "mpesa_passkey": PASSKEY,
        "mpesa_callback_base_url": "",
        "mpesa_callback_token": TOKEN,
        "mpesa_transaction_type": "CustomerPayBillOnline",
        "mpesa_till_number": "",
    }.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(mpesa_service, "QUERY_INTERVAL", timedelta(0))
    fake = FakeDaraja()
    daraja.set_client(daraja.DarajaClient(s, transport=httpx.MockTransport(fake.handler)))
    yield fake
    daraja.set_client(None)


def callback(client, token, cid, code=0, receipt="SKJ7RT61SV", amount=245):  # type: ignore[no-untyped-def]
    cb = {
        "MerchantRequestID": "x",
        "CheckoutRequestID": cid,
        "ResultCode": code,
        "ResultDesc": "done",
    }
    if code == 0:
        cb["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
                {"Name": "TransactionDate", "Value": 20261119102115},
                {"Name": "PhoneNumber", "Value": 254712345678},
            ]
        }
    return client.post(
        f"/api/v1/payments/mpesa/callback/{token}", json={"Body": {"stkCallback": cb}}
    )


def pay_sale(client, headers, product, payment_id):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/sales",
        headers=headers,
        json={
            "client_request_id": str(uuid.uuid4()),
            "items": [{"product_id": product["id"], "quantity": "1"}],
            "payment_method": "MPESA",
            "mpesa_payment_id": payment_id,
        },
    )


# --- unit-level rules ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", ["0712345678", "0712 345 678", "+254712345678", "254712345678", "712345678"]
)
def test_phone_numbers_are_normalised(raw: str) -> None:
    assert mpesa_service.normalise_phone(raw) == "254712345678"


def test_new_01_prefix_numbers_are_accepted() -> None:
    assert mpesa_service.normalise_phone("0110 123 456") == "254110123456"


@pytest.mark.parametrize("raw", ["", "12345", "0812345678", "07123456789", "+1 202 555 0100"])
def test_non_kenyan_mobile_numbers_are_refused(raw: str) -> None:
    with pytest.raises(ValidationFailed):
        mpesa_service.normalise_phone(raw)


def test_amount_is_rounded_up_to_whole_shillings() -> None:
    from decimal import Decimal

    assert mpesa_service.whole_shillings(Decimal("194.50")) == 195
    assert mpesa_service.whole_shillings(Decimal("195.00")) == 195


def test_callback_settings_checked_in_production() -> None:
    s = get_settings().model_copy(
        update={
            "environment": "production",
            "jwt_secret": "x" * 40,
            "database_url": "postgresql+psycopg://a:Vq8rT2mW9xK4pL7z@db/x",
            "mpesa_callback_base_url": "http://shop.example.com",
            "mpesa_callback_token": "short",
        }
    )
    problems = " ".join(production_config_problems(s))
    assert "https://" in problems and "MPESA_CALLBACK_TOKEN" in problems


# --- API ----------------------------------------------------------------------------------


def test_not_configured_is_explained(client: TestClient, shop) -> None:
    assert client.get("/api/v1/store", headers=shop["cashier"]).json()["mpesa_stk_enabled"] is False
    r = client.post(PUSH, headers=shop["cashier"], json={"phone": "0712345678", "amount": "245"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "MPESA_NOT_CONFIGURED"


def test_prompt_sends_a_correct_daraja_request(client: TestClient, shop, mpesa) -> None:
    assert client.get("/api/v1/store", headers=shop["cashier"]).json()["mpesa_stk_enabled"] is True
    r = client.post(
        PUSH, headers=shop["cashier"], json={"phone": "0712 345 678", "amount": "194.50"}
    )
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["status"] == "PENDING" and out["amount"] == 195 and out["phone"] == "254712***678"
    path, body = mpesa.requests[0]
    assert path == "/mpesa/stkpush/v1/processrequest"
    assert body["Amount"] == 195 and body["PhoneNumber"] == "254712345678" == body["PartyA"]
    assert body["BusinessShortCode"] == "174379" == body["PartyB"]
    assert body["TransactionType"] == "CustomerPayBillOnline"
    assert base64.b64decode(body["Password"]).decode() == f"174379{PASSKEY}{body['Timestamp']}"
    assert len(body["Timestamp"]) == 14 and len(body["AccountReference"]) <= 12
    assert body["CallBackURL"] == mpesa_service.PLACEHOLDER_CALLBACK  # no public address set


def test_buy_goods_till_pays_the_till_number(client: TestClient, shop, mpesa, monkeypatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "mpesa_transaction_type", "CustomerBuyGoodsOnline")
    monkeypatch.setattr(s, "mpesa_till_number", "5123456")
    client.post(PUSH, headers=shop["cashier"], json={"phone": "0712345678", "amount": "70"})
    body = mpesa.requests[0][1]
    assert body["TransactionType"] == "CustomerBuyGoodsOnline" and body["PartyB"] == "5123456"


def test_callback_url_uses_the_public_address_when_set(
    client: TestClient, shop, mpesa, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "mpesa_callback_base_url", "https://shop.example.com/")
    client.post(PUSH, headers=shop["cashier"], json={"phone": "0712345678", "amount": "70"})
    assert (
        mpesa.requests[0][1]["CallBackURL"]
        == f"https://shop.example.com/api/v1/payments/mpesa/callback/{TOKEN}"
    )


def test_result_by_query_then_pay_the_sale_once(client: TestClient, shop, mpesa) -> None:
    h = shop["cashier"]
    pid = client.post(PUSH, headers=h, json={"phone": "0712345678", "amount": "245"}).json()["id"]
    assert client.get(f"/api/v1/payments/mpesa/{pid}", headers=h).json()["status"] == "PENDING"
    cid = next(iter(mpesa.results))
    mpesa.results[cid] = ("0", "The service request is processed successfully.")
    paid = client.get(f"/api/v1/payments/mpesa/{pid}", headers=h).json()
    assert paid["status"] == "SUCCESS" and paid["result_desc"] == "Paid"

    sale = pay_sale(client, h, shop["sugar"], pid)
    assert sale.status_code == 201, sale.text
    assert (
        sale.json()["payment_method"] == "MPESA"
        and sale.json()["payment_reference"] == f"STK {cid}"
    )
    again = pay_sale(client, h, shop["sugar"], pid)
    assert again.status_code == 409 and again.json()["error"]["code"] == "MPESA_PAYMENT_USED"


def test_result_by_callback_records_the_receipt(client: TestClient, shop, mpesa) -> None:
    h = shop["cashier"]
    pid = client.post(PUSH, headers=h, json={"phone": "0712345678", "amount": "245"}).json()["id"]
    cid = next(iter(mpesa.results))
    assert callback(client, "wrong-token", cid).status_code == 404
    assert client.get(f"/api/v1/payments/mpesa/{pid}", headers=h).json()["status"] == "PENDING"
    r = callback(client, TOKEN, cid)
    assert r.status_code == 200 and r.json() == {"ResultCode": 0, "ResultDesc": "Accepted"}
    out = client.get(f"/api/v1/payments/mpesa/{pid}", headers=h).json()
    assert out["status"] == "SUCCESS" and out["mpesa_receipt_number"] == "SKJ7RT61SV"
    # A late or repeated callback cannot change a final result.
    callback(client, TOKEN, cid, code=1032)
    assert client.get(f"/api/v1/payments/mpesa/{pid}", headers=h).json()["status"] == "SUCCESS"
    sale = pay_sale(client, h, shop["sugar"], pid)
    assert sale.status_code == 201 and sale.json()["payment_reference"] == "SKJ7RT61SV"


def test_callback_for_unknown_request_is_ignored(client: TestClient, mpesa) -> None:
    assert callback(client, TOKEN, "ws_CO_unknown").status_code == 200


def test_underpaid_callback_is_not_success(client: TestClient, shop, mpesa) -> None:
    h = shop["cashier"]
    pid = client.post(PUSH, headers=h, json={"phone": "0712345678", "amount": "245"}).json()["id"]
    callback(client, TOKEN, next(iter(mpesa.results)), amount=10)
    assert client.get(f"/api/v1/payments/mpesa/{pid}", headers=h).json()["status"] == "FAILED"


@pytest.mark.parametrize(
    ("code", "status", "words"),
    [
        ("1032", "CANCELLED", "cancelled"),
        ("1037", "TIMEOUT", "could not be reached"),
        ("1", "FAILED", "balance"),
        ("2001", "FAILED", "PIN"),
    ],
)
def test_unsuccessful_results_are_explained_and_cannot_pay(
    client: TestClient, shop, mpesa, code, status, words
) -> None:
    h = shop["cashier"]
    pid = client.post(PUSH, headers=h, json={"phone": "0712345678", "amount": "245"}).json()["id"]
    mpesa.results[next(iter(mpesa.results))] = (code, "whatever Safaricom says")
    out = client.get(f"/api/v1/payments/mpesa/{pid}", headers=h).json()
    assert out["status"] == status and words in out["result_desc"]
    r = pay_sale(client, h, shop["sugar"], pid)
    assert r.status_code == 422 and r.json()["error"]["code"] == "MPESA_PAYMENT_INVALID"


def test_payment_smaller_than_sale_is_refused(client: TestClient, shop, mpesa) -> None:
    h = shop["cashier"]
    pid = client.post(PUSH, headers=h, json={"phone": "0712345678", "amount": "70"}).json()["id"]
    mpesa.results[next(iter(mpesa.results))] = ("0", "ok")
    client.get(f"/api/v1/payments/mpesa/{pid}", headers=h)
    r = pay_sale(client, h, shop["sugar"], pid)  # sugar costs 245
    assert r.status_code == 422 and r.json()["error"]["code"] == "MPESA_AMOUNT_SHORT"


def test_another_cashier_cannot_see_or_use_a_payment(client: TestClient, shop, mpesa) -> None:
    pid = client.post(
        PUSH, headers=shop["cashier"], json={"phone": "0712345678", "amount": "245"}
    ).json()["id"]
    mpesa.results[next(iter(mpesa.results))] = ("0", "ok")
    assert client.get(f"/api/v1/payments/mpesa/{pid}", headers=shop["cashier2"]).status_code == 404
    assert pay_sale(client, shop["cashier2"], shop["sugar"], pid).status_code == 422


def test_only_sellers_can_send_prompts(client: TestClient, shop, mpesa, auth_headers) -> None:
    _, officer = auth_headers("inventory_officer")
    assert (
        client.post(PUSH, headers=officer, json={"phone": "0712345678", "amount": "70"}).status_code
        == 403
    )
    assert client.post(PUSH, json={"phone": "0712345678", "amount": "70"}).status_code == 401


def test_invalid_phone_is_refused_before_calling_safaricom(client: TestClient, shop, mpesa) -> None:
    r = client.post(PUSH, headers=shop["cashier"], json={"phone": "0812345678", "amount": "70"})
    assert r.status_code == 422 and mpesa.requests == []


def test_safaricom_rejection_is_shown(client: TestClient, shop, mpesa) -> None:
    mpesa.reject_push = {
        "requestId": "1",
        "errorCode": "400.002.02",
        "errorMessage": "Bad Request - Invalid PhoneNumber",
    }
    r = client.post(PUSH, headers=shop["cashier"], json={"phone": "0712345678", "amount": "70"})
    assert r.status_code == 202 and r.json()["status"] == "FAILED"
    assert "Invalid PhoneNumber" in r.json()["result_desc"]


def test_safaricom_unreachable_leaves_nothing_behind(client: TestClient, shop, mpesa, db) -> None:
    from sqlalchemy import func, select

    from app.models import MpesaPayment

    mpesa.down = True
    r = client.post(PUSH, headers=shop["cashier"], json={"phone": "0712345678", "amount": "70"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MPESA_UNAVAILABLE"
    assert db.scalar(select(func.count()).select_from(MpesaPayment)) == 0


def test_manual_transaction_code_still_works(client: TestClient, shop, mpesa) -> None:
    r = client.post(
        "/api/v1/sales",
        headers=shop["cashier"],
        json={
            "client_request_id": str(uuid.uuid4()),
            "items": [{"product_id": shop["bread"]["id"], "quantity": "1"}],
            "payment_method": "MPESA",
            "payment_reference": "SKD4H2L9QX",
        },
    )
    assert r.status_code == 201 and r.json()["payment_reference"] == "SKD4H2L9QX"
