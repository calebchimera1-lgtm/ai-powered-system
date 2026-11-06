"""Safe handling of uploaded product images.

The file type is decided by the actual bytes (magic numbers), not the filename or the
browser's Content-Type. Every image is decoded and re-encoded by Pillow, which drops
EXIF/GPS metadata and anything hidden after the image data, and resized for the web.
"""

import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAGIC = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"RIFF": "webp",  # followed by size and "WEBP"
}
MAX_PIXELS = 40_000_000  # refuse decompression bombs
MAX_SIDE = 800


class ImageRejected(ValueError):
    pass


def sniff(data: bytes) -> str | None:
    for magic, kind in MAGIC.items():
        if data.startswith(magic):
            if kind == "webp" and data[8:12] != b"WEBP":
                return None
            return kind
    return None


def process_product_image(data: bytes, *, max_bytes: int) -> bytes:
    """Validate and re-encode as WebP. Raises ImageRejected with a user-facing reason."""
    if len(data) == 0:
        raise ImageRejected("The file is empty.")
    if len(data) > max_bytes:
        raise ImageRejected(f"The image is larger than {max_bytes // (1024 * 1024)} MB.")
    if sniff(data) is None:
        raise ImageRejected("Only JPEG, PNG or WebP images are accepted.")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=82, method=4)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageRejected("The image could not be read. Try another photo.") from exc


def save_product_image(storage_dir: Path, data: bytes) -> str:
    """Store under an unguessable name; returns the relative path."""
    folder = storage_dir / "products"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.webp"
    (folder / name).write_bytes(data)
    return f"products/{name}"


def delete_stored(storage_dir: Path, relative: str | None) -> None:
    if not relative:
        return
    path = (storage_dir / relative).resolve()
    if storage_dir.resolve() in path.parents and path.is_file():
        path.unlink()
