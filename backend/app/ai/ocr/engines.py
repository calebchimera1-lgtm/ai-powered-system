"""OCR engines and PDF text extraction behind one small interface.

Tesseract is the default: CPU-only, ~150 MB RAM per page, and it returns per-word boxes
and confidences, which the parser needs. Another engine (e.g. PaddleOCR) can be added by
implementing `read(image) -> list[Word]`.
"""

import io
from typing import Protocol

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
import pytesseract

from app.ai.ocr.types import Word

PDF_RENDER_DPI = 300
MAX_PDF_PAGES = 5


class OCREngine(Protocol):
    name: str

    def read(self, image: np.ndarray) -> list[Word]: ...


class TesseractEngine:
    """Tesseract 5 (LSTM). psm 6 treats the page as one block of text, which keeps table
    rows together; preserve_interword_spaces helps column splitting."""

    name = "tesseract"

    def __init__(self, lang: str = "eng", psm: int = 6) -> None:
        self.config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"
        self.lang = lang

    def read(self, image: np.ndarray) -> list[Word]:
        data = pytesseract.image_to_data(
            image, lang=self.lang, config=self.config, output_type=pytesseract.Output.DICT
        )
        words = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:
                continue
            words.append(
                Word(
                    text=text,
                    conf=conf,
                    left=int(data["left"][i]),
                    top=int(data["top"][i]),
                    width=int(data["width"][i]),
                    height=int(data["height"][i]),
                )
            )
        return words


def pdf_page_count(data: bytes) -> int:
    pdf = pdfium.PdfDocument(data)
    try:
        return len(pdf)
    finally:
        pdf.close()


def pdf_text_words(data: bytes, max_pages: int = MAX_PDF_PAGES) -> list[list[Word]]:
    """Words from a PDF's text layer, per page (empty pages for scanned PDFs).

    Coordinates are scaled to the 300-dpi render so they line up with page images."""
    scale = PDF_RENDER_DPI / 72
    pages: list[list[Word]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:max_pages]:
            words = []
            for w in page.extract_words(keep_blank_chars=False, use_text_flow=False):
                words.append(
                    Word(
                        text=w["text"],
                        conf=100.0,
                        left=int(w["x0"] * scale),
                        top=int(w["top"] * scale),
                        width=int((w["x1"] - w["x0"]) * scale),
                        height=int((w["bottom"] - w["top"]) * scale),
                    )
                )
            pages.append(words)
    return pages


def render_pdf(data: bytes, max_pages: int = MAX_PDF_PAGES) -> list[np.ndarray]:
    """Rasterise PDF pages to BGR images at 300 dpi (for scanned PDFs and the viewer)."""
    pdf = pdfium.PdfDocument(data)
    images = []
    try:
        for i in range(min(len(pdf), max_pages)):
            bitmap = pdf[i].render(scale=PDF_RENDER_DPI / 72)
            rgb = np.asarray(bitmap.to_pil().convert("RGB"))
            images.append(rgb[:, :, ::-1].copy())
    finally:
        pdf.close()
    return images
