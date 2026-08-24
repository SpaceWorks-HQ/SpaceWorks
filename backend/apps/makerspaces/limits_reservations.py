import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.makerspaces.domain_verification import is_self_host
from apps.makerspaces.limits_core import resource_limit

logger = logging.getLogger(__name__)


def reserve_notification_quota(makerspace, channel) -> bool:
    if is_self_host():
        return True
    limit = resource_limit(makerspace, channel)
    if limit is None:
        return True
    try:
        from apps.integrations.models import DailyNotificationCounter

        with transaction.atomic():
            counter, _ = DailyNotificationCounter.objects.get_or_create(
                makerspace=makerspace, channel=channel, day=timezone.now().date()
            )
            counter = DailyNotificationCounter.objects.select_for_update().get(pk=counter.pk)
            if counter.count >= limit:
                return False
            counter.count += 1
            counter.save(update_fields=["count"])
            return True
    except Exception:
        details = {"makerspace_id": makerspace.pk, "channel": channel}
        logger.exception("notification_limit_check_failed", extra=details)
        return True


def reserve_platform_otp_quota() -> bool:
    """Reserve one globally capped platform OTP email in managed mode."""
    if is_self_host():
        return True
    limit = settings.MANAGED_RESOURCE_LIMITS.get("otp_email")
    if limit is None:
        return True
    try:
        from apps.accounts.models import DailyOtpEmailCounter

        with transaction.atomic():
            counter, _ = DailyOtpEmailCounter.objects.get_or_create(
                day=timezone.now().date()
            )
            counter = DailyOtpEmailCounter.objects.select_for_update().get(pk=counter.pk)
            if counter.count >= limit:
                return False
            counter.count += 1
            counter.save(update_fields=["count"])
            return True
    except Exception:
        logger.exception("platform_otp_limit_check_failed")
        return True


def reserve_platform_otp_sms_quota() -> bool:
    """Reserve one platform auth/OTP text against the daily cap.

    Unlike reserve_platform_otp_quota, this **also applies on self-host**, and that
    asymmetry is the point: an email OTP costs a self-hoster nothing, while every text
    is billed by their SMS vendor. A loop against the OTP endpoint would spend a real
    balance, so the cap protects the operator rather than the platform. It is a
    per-day ceiling on cost, not a fair-use limit.

    Managed mode may tighten it further via MANAGED_RESOURCE_LIMITS["otp_sms"].
    """
    limit = getattr(settings, "OTP_SMS_DAILY_CAP", None)
    if not is_self_host():
        managed = settings.MANAGED_RESOURCE_LIMITS.get("otp_sms")
        if managed is not None:
            limit = managed if limit is None else min(limit, managed)
    if limit is None:
        return True
    try:
        from apps.integrations.models_sms import DailyOtpSmsCounter

        with transaction.atomic():
            counter, _ = DailyOtpSmsCounter.objects.get_or_create(
                day=timezone.now().date()
            )
            counter = DailyOtpSmsCounter.objects.select_for_update().get(pk=counter.pk)
            if counter.count >= limit:
                return False
            counter.count += 1
            counter.save(update_fields=["count"])
            return True
    except Exception:
        # Fail OPEN, matching its email twin: a broken counter must not lock every
        # member out of signing in. The cost ceiling is a guard, not a security
        # control -- the security controls are the cooldown and the attempt cap.
        logger.exception("platform_otp_sms_limit_check_failed")
        return True
