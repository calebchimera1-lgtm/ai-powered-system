"""Serves stored product images.

Product photos are not sensitive, and <img> tags cannot send the Authorization header,
so these are public but stored under unguessable random names. Sensitive uploads (supplier
invoices, Phase 4) will be served through authenticated endpoints instead.
"""

import re

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.exceptions import NotFoundError

router = APIRouter(prefix="/media", tags=["Media"])

NAME_RE = re.compile(r"^[0-9a-f]{32}\.webp$")


@router.get("/products/{name}", response_class=FileResponse)
def product_image(name: str) -> FileResponse:
    if not NAME_RE.match(name):
        raise NotFoundError("Image not found")
    path = get_settings().storage_dir / "products" / name
    if not path.is_file():
        raise NotFoundError("Image not found")
    return FileResponse(
        path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000"}
    )
