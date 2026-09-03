from io import BytesIO
from pathlib import Path

import segno

from apps.events.badge_templates import page_layout


def _register_fonts():
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = Path(reportlab.__file__).parent / "fonts"
    if "BadgeVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("BadgeVera", fonts / "Vera.ttf"))
        pdfmetrics.registerFont(TTFont("BadgeVeraBold", fonts / "VeraBd.ttf"))


def _fit_text(value, font_name, font_size, width):
    from reportlab.pdfbase import pdfmetrics

    text = " ".join(value.split())
    if pdfmetrics.stringWidth(text, font_name, font_size) <= width:
        return text
    suffix = "..."
    while text and pdfmetrics.stringWidth(text + suffix, font_name, font_size) > width:
        text = text[:-1]
    return text.rstrip() + suffix


def _qr_image(payload):
    from reportlab.lib.utils import ImageReader

    stream = BytesIO()
    segno.make(payload, error="M").save(stream, kind="png", scale=6, border=2)
    stream.seek(0)
    return ImageReader(stream), stream


def _draw_badge(canvas, snapshot, template, x, y, width, height):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm

    padding = 4 * mm
    canvas.setStrokeColor(HexColor("#CBD5E1"))
    canvas.setFillColor(HexColor("#FFFFFF"))
    canvas.roundRect(x, y, width, height, 2.5 * mm, stroke=1, fill=1)
    qr_width = min(30 * mm, height - 2 * padding) if template["include_qr"] else 0
    text_width = width - 2 * padding - (qr_width + 3 * mm if qr_width else 0)
    text_x = x + padding
    cursor = y + height - padding
    align = template["text_align"]
    for index, (label, value) in enumerate(snapshot.fields):
        is_name = index == 0 and template["fields"][0] == "name"
        font = "BadgeVeraBold" if is_name else "BadgeVera"
        size = template["name_font_size_pt"] if is_name else template["font_size_pt"]
        label_size = max(6, template["font_size_pt"] - 2)
        if not is_name:
            cursor -= label_size + 1
            canvas.setFillColor(HexColor("#64748B"))
            canvas.setFont("BadgeVeraBold", label_size)
            label_text = _fit_text(label.upper(), "BadgeVeraBold", label_size, text_width)
            if align == "center":
                canvas.drawCentredString(text_x + text_width / 2, cursor, label_text)
            else:
                canvas.drawString(text_x, cursor, label_text)
        cursor -= size + 2
        if cursor < y + padding:
            break
        canvas.setFillColor(HexColor("#0F172A"))
        canvas.setFont(font, size)
        fitted = _fit_text(value or "-", font, size, text_width)
        if align == "center":
            canvas.drawCentredString(text_x + text_width / 2, cursor, fitted)
        else:
            canvas.drawString(text_x, cursor, fitted)
        cursor -= 3
    if qr_width:
        image, stream = _qr_image(snapshot.checkin_token)
        canvas.drawImage(
            image, x + width - padding - qr_width, y + (height - qr_width) / 2,
            width=qr_width, height=qr_width, preserveAspectRatio=True, mask="auto",
        )
        stream.close()


def render_badges_pdf(template, snapshots, *, title):
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas

    _register_fonts()
    page_width_mm, page_height_mm, columns, rows = page_layout(template)
    page_size = (page_width_mm * mm, page_height_mm * mm)
    card_width = template["card_width_mm"] * mm
    card_height = template["card_height_mm"] * mm
    margin = template["margin_mm"] * mm
    gap = template["gap_mm"] * mm
    output = BytesIO()
    canvas = Canvas(output, pagesize=page_size, pageCompression=1, invariant=1)
    canvas.setTitle(title)
    per_page = columns * rows
    for index, snapshot in enumerate(snapshots):
        slot = index % per_page
        if index and slot == 0:
            canvas.showPage()
        column = slot % columns
        row = slot // columns
        x = margin + column * (card_width + gap)
        y = page_size[1] - margin - (row + 1) * card_height - row * gap
        _draw_badge(canvas, snapshot, template, x, y, card_width, card_height)
    canvas.showPage()
    canvas.save()
    return output.getvalue()
