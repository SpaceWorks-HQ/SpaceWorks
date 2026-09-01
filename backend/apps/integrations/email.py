import logging

from django.conf import settings
from django.core.mail import get_connection

from apps.integrations.smtp_validation import smtp_timeout_seconds, validate_smtp_endpoint

logger = logging.getLogger(__name__)


def makerspace_mail_connection(makerspace):
    smtp_host = (makerspace.smtp_host or "").strip()
    if not smtp_host:
        return platform_mail_connection()
    # use_ssl (implicit SSL, port 465) and use_tls (STARTTLS, port 587) are
    # mutually exclusive in Django's SMTP backend; prefer SSL when both are set.
    validate_smtp_endpoint(smtp_host, makerspace.smtp_port)
    use_ssl = makerspace.smtp_use_ssl
    use_tls = makerspace.smtp_use_tls and not use_ssl
    return (
        get_connection(
            host=smtp_host,
            port=makerspace.smtp_port,
            username=makerspace.smtp_username or None,
            password=makerspace.get_smtp_password() or None,
            use_tls=use_tls,
            use_ssl=use_ssl,
            timeout=smtp_timeout_seconds(),
        ),
        makerspace.smtp_from_email or settings.DEFAULT_FROM_EMAIL,
    )


def platform_mail_connection():
    """Connection + from-email for INSTANCE-WIDE auth mail (password resets).

    Uses the superadmin-configured PlatformEmailSettings when a host is set; otherwise
    returns (None, settings.DEFAULT_FROM_EMAIL) so Django's default EMAIL_BACKEND is used.
    NEVER uses per-makerspace SMTP. If a platform host IS configured but broken, do NOT
    silently fall back -- return its connection and let the caller's fail-safe handle errors.
    """
    from apps.integrations.models import PlatformEmailSettings

    cfg = PlatformEmailSettings.load()
    smtp_host = (cfg.smtp_host or "").strip()
    if not smtp_host:
        return None, settings.DEFAULT_FROM_EMAIL
    validate_smtp_endpoint(smtp_host, cfg.smtp_port)
    use_ssl = cfg.smtp_use_ssl
    use_tls = cfg.smtp_use_tls and not use_ssl
    return (
        get_connection(
            host=smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_username or None,
            password=cfg.get_smtp_password() or None,
            use_tls=use_tls,
            use_ssl=use_ssl,
            timeout=smtp_timeout_seconds(),
        ),
        cfg.from_email or settings.DEFAULT_FROM_EMAIL,
    )


def platform_email_configured() -> bool:
    from apps.integrations.models import PlatformEmailSettings

    cfg = PlatformEmailSettings.load()
    return bool((cfg.smtp_host or "").strip())


def _is_smtp_backend() -> bool:
    return settings.EMAIL_BACKEND.endswith("smtp.EmailBackend")


def email_enabled() -> bool:
    # Can we actually DELIVER mail? platform_mail_connection()/makerspace_mail_connection()
    # build the connection via Django get_connection(), which uses settings.EMAIL_BACKEND as
    # the backend CLASS. So a configured SMTP *host* (platform DB row or env EMAIL_HOST) only
    # delivers when EMAIL_BACKEND is the SMTP backend - with the console/locmem backend the
    # host args are ignored and mail is merely logged. Reporting enabled in that case would
    # advertise a Forgot-Password path that silently never sends (Codex Stage-4 P2).
    if _is_smtp_backend():
        return platform_email_configured() or bool((settings.EMAIL_HOST or "").strip())
    # Non-SMTP backend (console/locmem): a dev convenience only, and only under DEBUG.
    return settings.DEBUG and (
        settings.EMAIL_BACKEND.endswith("console.EmailBackend")
        or settings.EMAIL_BACKEND.endswith("locmem.EmailBackend")
    )


def send_password_reset_email(recipient, reset_url):
    from apps.integrations.dispatch import dispatch_email

    subject = "Reset your password"
    body = (
        "We received a request to reset your password.\n\n"
        f"Reset it here:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    log = dispatch_email(
        to_email=recipient,
        subject=subject,
        text_body=body,
        makerspace=None,
        stream="account",
        event="password_reset",
        audience="user",
        connection="platform",
        persist_body=False,
        sync=True,
    )
    return 1 if log.status == log.Status.SENT else 0


def send_password_reset_otp(recipient, code, *, expires_in_minutes):
    """Deliver a recovery code without persisting it or crossing a queue."""
    from apps.integrations.dispatch import dispatch_email

    subject = "Your password reset code"
    body = (
        "We received a request to reset your password.\n\n"
        f"Your password reset code is: {code}\n\n"
        f"This code expires in {expires_in_minutes} minutes and can be used once.\n\n"
        "If you did not request this, you can ignore this email."
    )
    log = dispatch_email(
        to_email=recipient,
        subject=subject,
        text_body=body,
        makerspace=None,
        stream="account",
        event="password_reset",
        audience="user",
        connection="platform",
        persist_body=False,
        sync=True,
    )
    return 1 if log.status == log.Status.SENT else 0


def send_email_verification_otp(recipient, code):
    from apps.integrations.dispatch import dispatch_email

    log = dispatch_email(
        to_email=recipient,
        subject="Verify your email",
        text_body=(
            "Use this code to verify your email address:\n\n"
            f"{code}\n\n"
            "This code expires in 10 minutes."
        ),
        makerspace=None,
        stream="account",
        event="email_verification",
        audience="user",
        connection="platform",
        persist_body=False,
        sync=True,
    )
    return 1 if log.status == log.Status.SENT else 0


def send_makerspace_email(
    makerspace,
    subject,
    body,
    recipients,
    html_body=None,
    *,
    stream="",
    event="",
    audience="",
    sync=False,
):
    from apps.integrations.dispatch import dispatch_email

    recipients = [recipient for recipient in recipients if recipient]
    if not recipients:
        return 0

    sent = 0
    for recipient in recipients:
        log = dispatch_email(
            to_email=recipient,
            subject=subject,
            text_body=body,
            html_body=html_body or "",
            makerspace=makerspace,
            stream=stream,
            event=event,
            audience=audience,
            connection="makerspace",
            sync=sync,
        )
        sent += 1 if log.status == log.Status.SENT else 0
    return sent

