"""Rebuild text lines from OCR words using their positions."""

from app.ai.ocr.types import Line, Word


def group_lines(words: list[Word], page: int = 1) -> list[Line]:
    """Cluster words into lines by vertical overlap, then sort each line left to right.

    Works on slightly tilted text too: a word joins the line whose vertical centre is
    within half a typical character height of its own."""
    if not words:
        return []
    heights = sorted(w.height for w in words)
    typical = heights[len(heights) // 2] or 10
    lines: list[list[Word]] = []
    centres: list[float] = []
    for w in sorted(words, key=lambda w: (w.cy, w.left)):
        best, best_d = None, None
        for i, c in enumerate(centres):
            d = abs(w.cy - c)
            if d <= typical * 0.55 and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is None:
            lines.append([w])
            centres.append(w.cy)
        else:
            lines[best].append(w)
            n = len(lines[best])
            centres[best] = (centres[best] * (n - 1) + w.cy) / n
    result = [Line(words=sorted(ws, key=lambda w: w.left), page=page) for ws in lines]
    return sorted(result, key=lambda ln: ln.top)
