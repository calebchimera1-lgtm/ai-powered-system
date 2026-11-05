"""Accounts created by scripts must pass the same validation as the API, so they stay
editable in the UI."""

import pytest

from app.schemas.users import UserUpdate
from scripts.seed_demo_users import DEMO_USERS


@pytest.mark.parametrize(("username", "name", "email", "role"), DEMO_USERS)
def test_demo_user_emails_are_valid(username: str, name: str, email: str, role: str) -> None:
    UserUpdate(full_name=name, email=email)


def test_reserved_local_domains_are_rejected() -> None:
    with pytest.raises(ValueError):
        UserUpdate(email="someone@store.local")
