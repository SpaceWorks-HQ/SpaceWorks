from io import BytesIO
from pathlib import Path


def _register_fonts():
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("CertificateVera", fonts / "Vera.ttf"))
    pdfmetrics.registerFont(TTFont("CertificateVeraBold", fonts / "VeraBd.ttf"))

def render_certificate_pdf(certificate):
    """Render snapshots with ReportLab's bundled, permissively licensed Vera font."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas

    _register_fonts()
    output = BytesIO()
    width, height = landscape(A4)
    # ``invariant`` removes volatile timestamps/IDs so a retry can prove that an
    # already-promoted final object contains the exact intended immutable PDF.
    canvas = Canvas(
        output,
        pagesize=(width, height),
        pageCompression=1,
        invariant=1,
    )
    canvas.setTitle(f"Attendance certificate {certificate.serial}")
    canvas.setLineWidth(1.5)
    canvas.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm)
    canvas.setFont("CertificateVeraBold", 28)
    canvas.drawCentredString(width / 2, height - 48 * mm, "Certificate of Attendance")
    canvas.setFont("CertificateVera", 14)
    canvas.drawCentredString(width / 2, height - 70 * mm, "This certifies that")
    canvas.setFont("CertificateVeraBold", 24)
    canvas.drawCentredString(width / 2, height - 91 * mm, certificate.recipient_name)
    canvas.setFont("CertificateVera", 14)
    canvas.drawCentredString(width / 2, height - 111 * mm, "attended")
    canvas.setFont("CertificateVeraBold", 20)
    canvas.drawCentredString(width / 2, height - 130 * mm, certificate.event_title)
    date_label = certificate.event_starts_at.strftime("%d %B %Y")
    canvas.setFont("CertificateVera", 13)
    canvas.drawCentredString(width / 2, height - 149 * mm, date_label)
    canvas.drawString(22 * mm, 24 * mm, certificate.issuer_name)
    canvas.setFont("CertificateVera", 8)
    canvas.drawRightString(
        width - 22 * mm,
        24 * mm,
        f"Serial {certificate.serial} · Revision {certificate.revision}",
    )
    canvas.showPage()
    canvas.save()
    return output.getvalue()
