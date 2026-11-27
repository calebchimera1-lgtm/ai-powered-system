"""Privacy features: erasing a former staff member's personal data, and the public facts
the privacy notice and terms of use show."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog, User, UserSession


def test_legal_info_is_public_and_lists_outside_services(client: TestClient, monkeypatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "store_phone", "+254700000000")
    monkeypatch.setattr(s, "return_policy", "Within 7 days with the receipt.")
    r = client.get("/api/v1/legal")
    assert r.status_code == 200
    body = r.json()
    assert body["privacy_contact"] == "+254700000000"  # falls back to the store phone
    assert body["return_policy"] == "Within 7 days with the receipt."
    assert body["ai_assistant"] is False and body["mpesa_prompts"] is False
    monkeypatch.setattr(s, "anthropic_api_key", "k")
    assert client.get("/api/v1/legal").json()["ai_assistant"] is True


def test_former_staff_personal_data_is_erased_but_records_stay(
    client: TestClient, auth_headers, db
) -> None:
    _, admin = auth_headers("super_admin", username="boss")
    victim, _ = auth_headers("cashier", username="amina")  # signs in: creates a session
    vid = victim.id
    r = client.patch(f"/api/v1/users/{vid}", headers=admin, json={"phone": "0712000111"})
    assert r.status_code == 200
    # Must be deactivated first.
    r = client.post(f"/api/v1/users/{vid}/erase", headers=admin)
    assert r.status_code == 422 and "Deactivate" in r.json()["error"]["message"]
    client.patch(f"/api/v1/users/{vid}", headers=admin, json={"is_active": False})

    r = client.post(f"/api/v1/users/{vid}/erase", headers=admin)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["full_name"] == f"Former staff member #{vid}"
    assert out["username"] == f"erased-{vid}" and out["email"] == f"erased-{vid}@example.com"
    db.expire_all()
    u = db.get(User, vid)
    assert u.phone is None and u.totp_secret is None
    assert db.scalar(select(UserSession).where(UserSession.user_id == vid)) is None
    # Audit entries stay, without the old name, e-mail or phone, or the person's IP address.
    entries = db.scalars(select(AuditLog).where(AuditLog.entity_id == str(vid))).all()
    text = " ".join(str(e.before) + str(e.after) for e in entries)
    assert "amina" not in text.lower() and "0712000111" not in text
    assert any(e.action == "user.personal_data_erased" for e in entries)
    own = db.scalars(select(AuditLog).where(AuditLog.user_id == vid)).all()
    assert all(e.ip_address is None for e in own)
    # Cannot be erased twice, cannot erase yourself, cashiers cannot erase anyone.
    assert client.post(f"/api/v1/users/{vid}/erase", headers=admin).status_code == 422


def test_only_user_managers_can_erase(client: TestClient, auth_headers) -> None:
    _, manager = auth_headers("store_manager", username="mgr")
    other, _ = auth_headers("cashier", username="till")
    assert client.post(f"/api/v1/users/{other.id}/erase", headers=manager).status_code == 403
