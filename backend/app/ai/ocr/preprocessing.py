"""OpenCV image preparation for OCR.

Steps (each one is reported, so the review screen and the project report can show what
was done to a photo):

1. Decode, apply the camera's EXIF rotation, and resize so text is a readable size
   (longest side <= 2600 px keeps memory low; small images are enlarged).
2. Measure quality: sharpness (variance of the Laplacian), brightness and contrast.
3. Find the paper: edge detection + the largest four-cornered contour; if it covers a
   reasonable part of the photo, a perspective transform flattens it.
4. Straighten: estimate the text angle from the minimum-area rectangle around ink pixels
   and rotate it level (up to +/- 15 degrees).
5. Clean: remove noise, even out lighting (CLAHE), then adaptive thresholding to black
   text on white, which Tesseract reads best.
"""

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.ai.ocr.types import Quality

MAX_SIDE = 2600
MIN_WIDTH = 1400

# Thresholds chosen on the synthetic dataset; documented in docs/ai/ocr.md.
BLUR_WARN = 60.0
DARK_WARN = 70.0
BRIGHT_WARN = 235.0
FAINT_INK = 110.0  # darkest 1% of pixels lighter than this: text is washed out


@dataclass
class Prepared:
    image: np.ndarray  # cleaned, binarised image for OCR
    display: np.ndarray  # straightened colour image for the review screen
    quality: Quality
    steps: list[str] = field(default_factory=list)


def decode(data: bytes) -> np.ndarray:
    """Bytes -> BGR array, honouring EXIF orientation from phone cameras."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def _resize(img: np.ndarray, steps: list[str]) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        scale = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        steps.append(f"resized down x{scale:.2f}")
    elif w < MIN_WIDTH:
        scale = MIN_WIDTH / w
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        steps.append(f"resized up x{scale:.2f}")
    return img


def measure(gray: np.ndarray) -> Quality:
    q = Quality(
        blur=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        brightness=float(gray.mean()),
        contrast=float(gray.std()),
        height=gray.shape[0],
        width=gray.shape[1],
    )
    # How dark is the darkest ink? On a readable page the darkest 1% of pixels is near
    # black. Average brightness alone misleads: white paper is naturally bright.
    ink = float(np.percentile(gray, 1))
    blurry = q.blur < BLUR_WARN
    if blurry:
        q.problems.append("The photo looks blurry. Hold the phone steady and retake it.")
    if q.brightness < DARK_WARN:
        q.problems.append("The photo is too dark. Use more light.")
    elif ink > FAINT_INK and not blurry:  # blur also lightens ink; one message is enough
        if q.brightness > BRIGHT_WARN:
            q.problems.append("The photo is over-exposed. Avoid glare or direct light.")
        else:
            q.problems.append("The text is faint (low contrast).")
    # Simple 0..1 score: penalise each problem.
    q.score = max(0.0, 1.0 - 0.3 * len(q.problems))
    return q


def _order_corners(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype=np.float32,
    )


def find_document(img: np.ndarray) -> np.ndarray | None:
    """Corners of the paper if a clear four-sided outline is found, else None."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    small_scale = 800 / max(gray.shape)
    small = cv2.resize(gray, None, fx=small_scale, fy=small_scale) if small_scale < 1 else gray
    if small_scale >= 1:
        small_scale = 1.0
    blur = cv2.GaussianBlur(small, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_total = small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(c)
        if area < 0.25 * area_total:
            break
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            # Ignore outlines that are basically the photo frame itself.
            if area > 0.97 * area_total:
                return None
            return _order_corners(approx.reshape(4, 2).astype(np.float32) / small_scale)
    return None


def flatten(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    matrix = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(
        img, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def estimate_skew(gray: np.ndarray) -> float:
    """Angle (degrees) of the text lines, from the rotated rectangles around text rows."""
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # Join characters into horizontal text blobs so each blob's angle follows its line.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, gray.shape[1] // 60), 3))
    blobs = cv2.dilate(binary, kernel, iterations=1)
    contours, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles, weights = [], []
    for c in contours:
        (_, _), (w, h), angle = cv2.minAreaRect(c)
        # OpenCV reports angles in [0, 90); when it calls the long side the "height",
        # the text line runs at angle - 90.
        if w < h:
            w, h = h, w
            angle -= 90
        if angle > 45:
            angle -= 90
        elif angle < -45:
            angle += 90
        if w < gray.shape[1] * 0.08 or w / max(h, 1) < 3:
            continue  # not a text line
        if abs(angle) <= 15:
            angles.append(angle)
            weights.append(w)
    if not angles:
        return 0.0
    order = np.argsort(angles)
    a, wts = np.array(angles)[order], np.array(weights)[order]
    cumulative = np.cumsum(wts)
    return float(a[np.searchsorted(cumulative, cumulative[-1] / 2)])  # weighted median


def rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    matrix[0, 2] += nw / 2 - w / 2
    matrix[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(
        img, matrix, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def prepare(img: np.ndarray, *, is_scan: bool = False) -> Prepared:
    """Full preparation. `is_scan` skips document detection for rendered PDF pages."""
    steps: list[str] = []
    img = _resize(img, steps)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    quality = measure(gray)

    if not is_scan:
        corners = find_document(img)
        if corners is not None:
            img = flatten(img, corners)
            quality.document_detected = True
            steps.append("paper outline found; perspective corrected")
            img = _resize(img, steps)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    skew = estimate_skew(gray)
    quality.skew_degrees = round(skew, 2)
    if abs(skew) >= 0.3:
        img = rotate(img, skew)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        steps.append(f"straightened by {skew:.1f} degrees")

    display = img
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
    binary = cv2.adaptiveThreshold(
        clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    # Morphological closing on the white background fills in tiny black specks (noise)
    # without eating into the strokes of real characters.
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    steps.append("denoised, contrast-equalised and binarised")
    return Prepared(image=binary, display=display, quality=quality, steps=steps)
