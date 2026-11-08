"""Management dashboard."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require
from app.core.permissions import P
from app.models import User
from app.schemas.dashboard import Dashboard
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

Viewer = Annotated[User, Depends(require(P.DASHBOARD_READ))]


@router.get("", response_model=Dashboard)
def dashboard(
    user: Viewer,
    db: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
) -> Dashboard:
    """Defaults to the last 30 days. Sales and stock value need finance permission;
    irregularities need anomaly permission."""
    d2 = date_to or dashboard_service.today()
    d1 = date_from or d2 - timedelta(days=29)
    codes = user.permission_codes
    return Dashboard.model_validate(
        dashboard_service.build(
            db,
            d1=d1,
            d2=d2,
            category_id=category_id,
            finance=P.FINANCE_READ.value in codes,
            anomalies=P.ANOMALIES_READ.value in codes,
        )
    )
