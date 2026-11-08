"""Render a Report as CSV, Excel (openpyxl) or PDF (ReportLab). Pure Python, no browser."""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Column kinds decide alignment and number format.
KINDS = ("text", "int", "qty", "money", "percent", "date", "datetime")


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"


@dataclass
class Report:
    title: str
    subtitle: str  # period and filters, in words
    columns: list[Column]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    summary: list[tuple[str, str]] = field(default_factory=list)  # label, formatted value
    landscape: bool = False


@dataclass
class Meta:
    store_name: str
    store_details: str
    generated_by: str
    generated_at: datetime


def fmt(value: Any, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return f"{Decimal(value):,.2f}"
    if kind == "qty":
        v = Decimal(value)
        return f"{v:,.0f}" if v == v.to_integral_value() else f"{v:,.2f}".rstrip("0").rstrip(".")
    if kind == "int":
        return f"{int(value):,}"
    if kind == "percent":
        return f"{Decimal(value):.1f}%"
    if kind == "date":
        return value.strftime("%d %b %Y") if isinstance(value, date) else str(value)
    if kind == "datetime":
        return value.strftime("%d %b %Y %H:%M") if isinstance(value, datetime) else str(value)
    return str(value)


def _plain(value: Any, kind: str) -> Any:
    """Machine-readable value for CSV: numbers without separators, ISO dates."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if kind in ("money", "qty", "percent") and value != "":
        # format(..., "f") avoids scientific notation ("2.4E+2") from normalize().
        return (
            format(Decimal(value).normalize(), "f") if kind != "money" else f"{Decimal(value):.2f}"
        )
    return value


def to_csv(report: Report, meta: Meta) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.label for c in report.columns])
    for row in report.rows:
        w.writerow([_plain(row.get(c.key), c.kind) for c in report.columns])
    if report.totals:
        w.writerow([_plain(report.totals.get(c.key), c.kind) for c in report.columns])
    # utf-8-sig: Excel opens the file with the right encoding (KES, names with accents).
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(report: Report, meta: Meta) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = report.title[:31]
    ws.append([report.title])
    ws["A1"].font = Font(size=14, bold=True)
    ws.append([f"{meta.store_name} · {report.subtitle}"])
    ws.append([f"Generated {meta.generated_at:%d %b %Y %H:%M} by {meta.generated_by}"])
    ws["A3"].font = Font(color="666666", size=9)
    row = 4
    for label, value in report.summary:
        row += 1
        ws.cell(row=row, column=1, value=label).font = Font(color="444444")
        ws.cell(row=row, column=2, value=value).font = Font(bold=True)
    row += 2
    header_row = row
    fill = PatternFill("solid", fgColor="E8F5EE")
    for i, c in enumerate(report.columns, 1):
        cell = ws.cell(row=row, column=i, value=c.label)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.border = Border(bottom=Side(style="thin", color="9CA3AF"))
        if c.kind not in ("text",):
            cell.alignment = Alignment(horizontal="right")
    formats = {
        "money": "#,##0.00",
        "qty": "#,##0.###",
        "int": "#,##0",
        "percent": '0.0"%"',
        "date": "dd mmm yyyy",
        "datetime": "dd mmm yyyy hh:mm",
    }

    def put(r: int, data: dict[str, Any], bold: bool = False) -> None:
        for i, c in enumerate(report.columns, 1):
            v = data.get(c.key)
            if isinstance(v, Decimal):
                v = float(v)
            if isinstance(v, datetime) and v.tzinfo is not None:
                v = v.replace(tzinfo=None)  # Excel has no time zones; values are store-local
            cell = ws.cell(row=r, column=i, value=v)
            if c.kind in formats:
                cell.number_format = formats[c.kind]
            if bold:
                cell.font = Font(bold=True)
                cell.border = Border(top=Side(style="thin", color="9CA3AF"))

    for data in report.rows:
        row += 1
        put(row, data)
    if report.totals:
        row += 1
        put(row, report.totals, bold=True)
    for note in report.notes:
        row += 2 if note is report.notes[0] else 1
        ws.cell(row=row, column=1, value=note).font = Font(italic=True, color="555555", size=9)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    for i, c in enumerate(report.columns, 1):
        width = max([len(c.label)] + [len(fmt(r.get(c.key), c.kind)) for r in report.rows[:500]])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 9), 45)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(report: Report, meta: Meta) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    size = landscape(A4) if report.landscape or len(report.columns) > 7 else A4
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=9.5)
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=TA_RIGHT)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    head_r = ParagraphStyle("headr", parent=head, alignment=TA_RIGHT)

    def footer(canvas, doc) -> None:  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(
            15 * mm,
            9 * mm,
            f"{meta.store_name} · {report.title} · generated "
            f"{meta.generated_at:%d %b %Y %H:%M} by {meta.generated_by}",
        )
        canvas.drawRightString(size[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=size,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=report.title,
        author=meta.store_name,
    )
    story: list[Any] = [
        Paragraph(
            meta.store_name,
            ParagraphStyle(
                "store", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#047857")
            ),
        ),
        Paragraph(
            report.title,
            ParagraphStyle("t", parent=styles["Heading1"], spaceBefore=2, spaceAfter=4),
        ),
        Paragraph(report.subtitle, small),
    ]
    if meta.store_details:
        story.append(Paragraph(meta.store_details, small))
    story.append(Spacer(1, 4 * mm))
    if report.summary:
        st = Table(
            [[Paragraph(k, cell), Paragraph(f"<b>{v}</b>", cell_r)] for k, v in report.summary],
            colWidths=[70 * mm, 45 * mm],
            hAlign="LEFT",
        )
        st.setStyle(
            TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story += [st, Spacer(1, 5 * mm)]

    numeric = [c.kind not in ("text", "date", "datetime") for c in report.columns]
    data = [
        [Paragraph(c.label, head_r if numeric[i] else head) for i, c in enumerate(report.columns)]
    ]
    for r in report.rows:
        data.append(
            [
                Paragraph(fmt(r.get(c.key), c.kind), cell_r if numeric[i] else cell)
                for i, c in enumerate(report.columns)
            ]
        )
    if report.totals:
        data.append(
            [
                Paragraph(
                    f"<b>{fmt(report.totals.get(c.key), c.kind)}</b>",
                    cell_r if numeric[i] else cell,
                )
                for i, c in enumerate(report.columns)
            ]
        )
    if len(data) == 1:
        story.append(Paragraph("No records for this period.", styles["Normal"]))
    else:
        width = size[0] - 30 * mm

        # Size columns by content: numbers and dates must never wrap; text takes the rest.
        def chars(c: Column) -> int:
            values = [len(fmt(r.get(c.key), c.kind)) for r in report.rows[:400]]
            if report.totals:
                values.append(len(fmt(report.totals.get(c.key), c.kind)))
            longest_word = max((len(w) for w in c.label.split()), default=4)
            need = max(values + [longest_word, 4])
            return min(need, 60) if c.kind == "text" else need

        need = [chars(c) * 5.0 + 14 for c in report.columns]  # ~5pt a char at 8pt + 2x6pt padding
        # Text columns keep at least ~12 characters; only the excess shrinks to fit.
        floor = [
            min(n, 12 * 5.0 + 14) if c.kind == "text" else n
            for n, c in zip(need, report.columns, strict=True)
        ]
        flexible = sum(n - f for n, f in zip(need, floor, strict=True))
        spare = width - sum(floor)
        scale = max(0.0, min(1.0, spare / flexible)) if flexible else 1.0
        col_w = [f + (n - f) * scale for n, f in zip(need, floor, strict=True)]
        if sum(col_w) > width:  # very wide report: shrink everything proportionally
            col_w = [w * width / sum(col_w) for w in col_w]
        elif sum(col_w) < width:  # stretch text columns to fill the page
            extra = width - sum(col_w)
            n_text = sum(1 for c in report.columns if c.kind == "text") or len(col_w)
            col_w = [
                w + (extra / n_text if (c.kind == "text" or n_text == len(col_w)) else 0)
                for w, c in zip(col_w, report.columns, strict=True)
            ]
        t = Table(data, colWidths=col_w, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f5ee")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#9ca3af")),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1 if not report.totals else -2),
                [colors.white, colors.HexColor("#f9fafb")],
            ),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]
        if report.totals:
            style.append(("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.HexColor("#6b7280")))
        t.setStyle(TableStyle(style))
        story.append(t)
    for note in report.notes:
        story += [Spacer(1, 2 * mm), Paragraph(note, small)]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


WRITERS = {
    "csv": (to_csv, "text/csv; charset=utf-8", "csv"),
    "xlsx": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": (to_pdf, "application/pdf", "pdf"),
}
