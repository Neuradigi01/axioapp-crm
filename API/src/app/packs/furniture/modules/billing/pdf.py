"""Furniture-pack: invoice PDF template.

Pure-Python reportlab — no system deps, runs in slim Docker images.
The output mirrors the in-store paper receipts most Indian furniture
showrooms hand out: branded header, INR formatting, GST line under
the totals, payment-method footer.

The renderer is wired into the core `pdf_registry` from this pack's
`__init__.py` at import time. Core never imports this file.
"""

from __future__ import annotations

import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.app.core.billing.models import Invoice, InvoiceLine

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _fmt_inr(value: Decimal | int | float | None) -> str:
    if value is None:
        return "-"
    try:
        n = Decimal(str(value))
    except Exception:
        return "-"
    # Indian grouping: last 3 digits, then groups of 2. We approximate
    # with the standard `locale`-free formatter and prepend the symbol.
    sign = "-" if n < 0 else ""
    n = abs(n)
    int_part, _, frac_part = f"{n:.2f}".partition(".")
    # Indian grouping
    if len(int_part) > 3:
        head = int_part[:-3]
        tail = int_part[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        int_grouped = ",".join(groups) + "," + tail
    else:
        int_grouped = int_part
    return f"{sign}₹{int_grouped}.{frac_part}"


async def render_invoice_pdf(
    invoice: Invoice,
    lines: list[InvoiceLine],
    org_meta: dict[str, str | None],
) -> tuple[bytes, str]:
    """Return `(pdf_bytes, filename)` for the supplied invoice."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Invoice #{invoice.number or 'DRAFT'}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "h1",
        parent=styles["Heading1"],
        fontName=_FONT_BOLD,
        fontSize=18,
        leading=22,
        spaceAfter=4,
    )
    h_sub = ParagraphStyle(
        "sub",
        parent=styles["Normal"],
        fontName=_FONT,
        fontSize=9,
        textColor=colors.HexColor("#52525b"),
        leading=12,
    )
    label = ParagraphStyle(
        "label",
        parent=styles["Normal"],
        fontName=_FONT_BOLD,
        fontSize=8,
        textColor=colors.HexColor("#71717a"),
        leading=10,
        spaceBefore=4,
    )
    body = ParagraphStyle(
        "body",
        parent=styles["Normal"],
        fontName=_FONT,
        fontSize=10,
        leading=14,
    )

    elements: list = []

    # Header
    elements.append(Paragraph("Tax Invoice", h1))
    elements.append(
        Paragraph(
            f"Invoice #{invoice.number or 'DRAFT'}"
            f" &nbsp;&nbsp;|&nbsp;&nbsp; Status: {invoice.status.value.upper()}",
            h_sub,
        )
    )
    issued_str = (
        invoice.issued_at.strftime("%d %b %Y, %H:%M") if invoice.issued_at else "Not yet issued"
    )
    elements.append(Paragraph(f"Issued: {issued_str}", h_sub))
    if org_meta.get("gst_number"):
        elements.append(Paragraph(f"GSTIN: {org_meta['gst_number']}", h_sub))
    elements.append(Spacer(1, 8 * mm))

    # Line items
    header = ["#", "Description", "Qty", "Unit", "Tax %", "Total"]
    data: list[list] = [header]
    for i, ln in enumerate(lines, start=1):
        data.append(
            [
                str(i),
                Paragraph(ln.description, body),
                str(ln.qty),
                _fmt_inr(ln.unit_price),
                f"{ln.tax_pct}%",
                _fmt_inr(ln.line_total),
            ]
        )
    table = Table(
        data,
        colWidths=[10 * mm, 80 * mm, 14 * mm, 26 * mm, 18 * mm, 32 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f4f5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#3f3f46")),
                ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#a1a1aa")),
                ("LINEBELOW", (0, -1), (-1, -1), 0.25, colors.HexColor("#e4e4e7")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#fafafa")],
                ),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 6 * mm))

    # Totals (right-aligned mini-table)
    totals_data = [
        ["Subtotal", _fmt_inr(invoice.subtotal)],
        [f"Tax ({invoice.tax_rate_snapshot or 0}%)", _fmt_inr(invoice.tax_amount)],
        [
            "Discount",
            "-" + _fmt_inr(invoice.discount_amount) if invoice.discount_amount else _fmt_inr(0),
        ],
        ["Total", _fmt_inr(invoice.total)],
    ]
    totals = Table(totals_data, colWidths=[40 * mm, 40 * mm], hAlign="RIGHT")
    totals.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor("#71717a")),
                ("FONTNAME", (0, -1), (-1, -1), _FONT_BOLD),
                ("FONTSIZE", (0, -1), (-1, -1), 12),
                ("TOPPADDING", (0, -1), (-1, -1), 4),
            ]
        )
    )
    elements.append(totals)
    elements.append(Spacer(1, 8 * mm))

    # Payment + notes
    if invoice.payment_method:
        elements.append(Paragraph(f"Payment method: {invoice.payment_method.value.upper()}", label))
    if invoice.notes:
        elements.append(Paragraph("Notes", label))
        elements.append(Paragraph(invoice.notes.replace("\n", "<br/>"), body))

    # Footer
    elements.append(Spacer(1, 12 * mm))
    elements.append(
        Paragraph(
            "Thank you for your purchase. All sales are subject to our standard return policy.",
            h_sub,
        )
    )

    doc.build(elements)
    pdf_bytes = buf.getvalue()
    buf.close()

    filename = f"invoice-{invoice.number or 'draft'}.pdf"
    return pdf_bytes, filename
