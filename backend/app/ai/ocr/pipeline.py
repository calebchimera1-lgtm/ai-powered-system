"""Run a document through the OCR stages: bytes in, lines + quality + page images out.

Kept free of database code so it can be unit-tested and evaluated on the synthetic
dataset (scripts/evaluate_ocr.py) exactly as it runs in production.
"""

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.ai.ocr import engines, preprocessing
from app.ai.ocr.layout import group_lines
from app.ai.ocr.parser import extract
from app.ai.ocr.types import Extraction, Line, Quality

PDF_TEXT_MIN_WORDS = 15


@dataclass
class DocumentRead:
    lines: list[Line]
    pages: list[bytes]  # page images (PNG, straightened) for the review screen
    quality: Quality
    engine: str
    steps: list[str] = field(default_factory=list)
    milliseconds: int = 0

    @property
    def raw_text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


def _png(img: np.ndarray, max_side: int = 1800) -> bytes:
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:
        raise ValueError("could not encode page image")
    return buf.tobytes()


def _ocr_best(engine: engines.OCREngine, prepared: preprocessing.Prepared) -> list:
    """OCR the cleaned binary image; if that reads poorly, also try the plain greyscale
    image and keep whichever Tesseract is more confident about."""
    words = engine.read(prepared.image)

    def strength(ws: list) -> float:
        return sum(w.conf for w in ws) / 100

    if not words or sum(w.conf for w in words) / len(words) < 80:
        gray = cv2.cvtColor(prepared.display, cv2.COLOR_BGR2GRAY)
        alt = engine.read(gray)
        if strength(alt) > strength(words):
            prepared.steps.append("greyscale image read better than the binarised one")
            return alt
    return words


def read_document(data: bytes, mime: str, engine: engines.OCREngine | None = None) -> DocumentRead:
    started = time.perf_counter()
    engine = engine or engines.TesseractEngine()
    lines: list[Line] = []
    pages: list[bytes] = []
    steps: list[str] = []
    quality = Quality(score=1.0)
    used = engine.name

    if mime == "application/pdf":
        text_pages = engines.pdf_text_words(data)
        rendered = engines.render_pdf(data)
        if sum(len(p) for p in text_pages) >= PDF_TEXT_MIN_WORDS:
            used = "pdf-text"
            steps.append("read the PDF's text layer (no OCR needed)")
            offset = 0
            for i, words in enumerate(text_pages, 1):
                for ln in group_lines(words, page=i):
                    for w in ln.words:
                        w.top += offset
                    lines.append(ln)
                offset += 100000
            pages = [_png(img) for img in rendered]
        else:
            steps.append("scanned PDF: pages rendered at 300 dpi for OCR")
            for i, img in enumerate(rendered, 1):
                prepared = preprocessing.prepare(img, is_scan=True)
                if i == 1:
                    quality = prepared.quality
                steps.extend(prepared.steps)
                lines.extend(group_lines(_ocr_best(engine, prepared), page=i))
                pages.append(_png(prepared.display))
    else:
        img = preprocessing.decode(data)
        prepared = preprocessing.prepare(img)
        quality = prepared.quality
        steps.extend(prepared.steps)
        lines = group_lines(_ocr_best(engine, prepared))
        pages = [_png(prepared.display)]

    return DocumentRead(
        lines=lines,
        pages=pages,
        quality=quality,
        engine=used,
        steps=steps,
        milliseconds=int((time.perf_counter() - started) * 1000),
    )


def process(
    data: bytes, mime: str, engine: engines.OCREngine | None = None
) -> tuple[DocumentRead, Extraction]:
    doc = read_document(data, mime, engine)
    return doc, extract(doc.lines)
