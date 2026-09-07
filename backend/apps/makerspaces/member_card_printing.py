"""Render member cards to PDF: one CR80 card or a sheet of them.

Nothing rendered is written to object storage — a PDF of names and faces would be a second
PII retention surface — so the response streams the bytes and the audit trail records the
print. Same reportlab/segno stack as the event badges.
"""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import segno

from apps.makerspaces.member_card_templates import page_layout


@dataclass(frozen=True)
class CardSnapshot:
    card_number: int
    printed_name: str
    makerspace_name: str
    issued_at: str
    membership_role: str
    qr_payload: str | None
    photo: bytes | None
    watermark: str = ""
    certifications: tuple = ()


def _register_fonts():
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = Path(reportlab.__file__).parent / "fonts"
    if "CardVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("CardVera", fonts / "Vera.ttf"))
        pdfmetrics.registerFont(TTFont("CardVeraBold", fonts / "VeraBd.ttf"))


def _fit(text, font, size, width):
    from reportlab.pdfbase import pdfmetrics

    value = " ".join((text or "").split())
    if pdfmetrics.stringWidth(value, font, size) <= width:
        return value
    while value and pdfmetrics.stringWidth(value + "...", font, size) > width:
        value = value[:-1]
    return value.rstrip() + "..."


def _qr_reader(payload):
    from reportlab.lib.utils import ImageReader

    stream = BytesIO()
    segno.make(payload, error="M").save(stream, kind="png", scale=6, border=1)
    stream.seek(0)
    return ImageReader(stream)


def _field_value(snapshot, key):
    return {
        "printed_name": snapshot.printed_name or "-",
        "card_number": f"No. {snapshot.card_number:05d}",
        "makerspace": snapshot.makerspace_name,
        "issued_at": snapshot.issued_at,
        "membership_role": snapshot.membership_role,
        "certifications": ", ".join(snapshot.certifications) or "-",
    }[key]


def _draw_card(canvas, snapshot, template, x, y, width, height):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    pad = 4 * mm
    canvas.setStrokeColor(HexColor("#CBD5E1"))
    canvas.setFillColor(HexColor("#FFFFFF"))
    canvas.roundRect(x, y, width, height, 3 * mm, stroke=1, fill=1)
    cursor_x = x + pad
    photo_w = 0
    if template["include_photo"]:
        photo_w = min(22 * mm, height - 2 * pad)
        if snapshot.photo:
            canvas.drawImage(ImageReader(BytesIO(snapshot.photo)), cursor_x, y + height - pad - photo_w, width=photo_w, height=photo_w, preserveAspectRatio=True, mask="auto")
        else:
            canvas.setFillColor(HexColor("#E2E8F0"))
            canvas.rect(cursor_x, y + height - pad - photo_w, photo_w, photo_w, stroke=0, fill=1)
        cursor_x += photo_w + 3 * mm
    qr_w = min(20 * mm, height - 2 * pad) if template["include_qr"] and snapshot.qr_payload else 0
    text_w = width - (cursor_x - x) - pad - (qr_w + 3 * mm if qr_w else 0)
    cursor_y = y + height - pad
    for index, key in enumerate(template["front_fields"]):
        font = "CardVeraBold" if index == 0 else "CardVera"
        size = template["name_font_size_pt"] if index == 0 else template["font_size_pt"]
        cursor_y -= size + 2
        if cursor_y < y + pad:
            break
        canvas.setFillColor(HexColor("#0F172A" if index == 0 else "#475569"))
        canvas.setFont(font, size)
        canvas.drawString(cursor_x, cursor_y, _fit(_field_value(snapshot, key), font, size, text_w))
    if qr_w:
        canvas.drawImage(_qr_reader(snapshot.qr_payload), x + width - pad - qr_w, y + pad, width=qr_w, height=qr_w, mask="auto")
    if snapshot.watermark:
        canvas.saveState()
        canvas.setFillColor(HexColor("#94A3B8"))
        canvas.setFont("CardVeraBold", 10)
        canvas.drawCentredString(x + width / 2, y + 2 * mm, snapshot.watermark)
        canvas.restoreState()


def _crop_marks(canvas, x, y, width, height):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm

    canvas.setStrokeColor(HexColor("#94A3B8"))
    canvas.setLineWidth(0.3)
    for cx, cy, dx, dy in ((x, y, -1, -1), (x + width, y, 1, -1), (x, y + height, -1, 1), (x + width, y + height, 1, 1)):
        canvas.line(cx + dx * 1 * mm, cy, cx + dx * 4 * mm, cy)
        canvas.line(cx, cy + dy * 1 * mm, cx, cy + dy * 4 * mm)


def render_cards_pdf(template, snapshots, *, title):
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas

    _register_fonts()
    page_w_mm, page_h_mm, columns, rows = page_layout(template)
    page = (page_w_mm * mm, page_h_mm * mm)
    card_w, card_h = template["card_width_mm"] * mm, template["card_height_mm"] * mm
    margin, gap = template["margin_mm"] * mm, template["gap_mm"] * mm
    output = BytesIO()
    canvas = Canvas(output, pagesize=page, pageCompression=1, invariant=1)
    canvas.setTitle(title)
    per_page = columns * rows
    for index, snapshot in enumerate(snapshots):
        slot = index % per_page
        if index and slot == 0:
            canvas.showPage()
        column, row = slot % columns, slot // columns
        x = margin + column * (card_w + gap)
        y = page[1] - margin - (row + 1) * card_h - row * gap
        _draw_card(canvas, snapshot, template, x, y, card_w, card_h)
        if template["crop_marks"] and template["page"] != "cr80":
            _crop_marks(canvas, x, y, card_w, card_h)
    if not snapshots:
        canvas.setFont("CardVera", 10)
        canvas.drawString(20 * mm, page[1] - 20 * mm, "No cards selected.")
    canvas.showPage()
    canvas.save()
    return output.getvalue()
