"""Render only immutable document snapshots; no live names or prices enter a PDF."""

from html import escape
from io import BytesIO
from pathlib import Path
from functools import partial


def render_document_pdf(document):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfgen.canvas import Canvas

    fonts = Path(reportlab.__file__).parent / "fonts"
    if "ReceiptVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ReceiptVera", fonts / "Vera.ttf"))
    style = ParagraphStyle("receipt", fontName="ReceiptVera", fontSize=10, leading=15)
    heading = ParagraphStyle("heading", parent=style, fontSize=20, leading=26, spaceAfter=16)
    def text(value, selected=style):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), selected)
    issuer = document.issuer
    story = [text(document.get_kind_display(), heading), text(issuer["name"]),
             text(issuer.get("address", "")), Spacer(1, 6 * mm),
             text(f"Document {document.number}"), text(f"Issued {document.issued_at.isoformat()}"),
             text(f"Payer: {document.payer_label}"),
             text(f"Money date: {document.money_at.isoformat()}"),
             text(f"Method: {document.settlement_method}"),
             text(f"Reference: {document.settlement_reference or '-'}"), Spacer(1, 8 * mm)]
    if issuer.get("tax_id"):
        story.append(text(f"Issuer identifier: {issuer['tax_id']}"))
    table = Table([
        [text("Description"), text("Quantity"), text("Amount")],
        *[[text(line["label"]), text(line["quantity"]), text(line["total"])] for line in document.lines],
    ], colWidths=[110 * mm, 22 * mm, 38 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#A0ACBC")),
    ]))
    story.extend([table, Spacer(1, 8 * mm),
                  text(f"Total: {document.currency.upper()} {document.amount}", heading),
                  text("Gross-only payment acknowledgement. No tax calculation is included."),
                  text(issuer.get("footer", ""))])
    output = BytesIO()
    def page_footer(canvas, pdf):
        canvas.setFont("ReceiptVera", 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(20 * mm, 12 * mm, f"{document.number} - Page {pdf.page}")
    SimpleDocTemplate(output, rightMargin=20 * mm, leftMargin=20 * mm,
                      title=document.number, pageCompression=1).build(
                          story, onFirstPage=page_footer, onLaterPages=page_footer,
                          canvasmaker=partial(Canvas, invariant=1))
    return output.getvalue()
