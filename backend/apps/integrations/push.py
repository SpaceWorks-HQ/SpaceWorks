import logging

from django.utils import timezone

from apps.integrations.models_push import PlatformPushSettings, PushDevice
from apps.integrations.push_fcm import PushProviderError, send_fcm
from apps.integrations.staff_notifications import staff_user_ids_for_feature

logger = logging.getLogger(__name__)


def push_configured():
    try:
        row = PlatformPushSettings.load()
        return bool(
            (row.fcm_configured and row.get_fcm_service_account())
            or (row.apns_configured and row.get_apns_private_key())
        )
    except Exception:
        return False


def deliver_native_push(log):
    # Additive master switch (plan A6): the platform credential check below still runs,
    # so enabling the feature on an unconfigured platform delivers nothing.
    from apps.makerspaces.platform import feature_enabled

    if log.makerspace_id and not feature_enabled(log.makerspace, "mobile.push"):
        return False
    settings_row = PlatformPushSettings.load()
    if not (settings_row.fcm_configured or settings_row.apns_configured):
        return False
    user_ids = staff_user_ids_for_feature(log.makerspace, log.feature, event=log.event)
    devices = PushDevice.objects.filter(
        makerspace=log.makerspace, user_id__in=user_ids, active=True,
        device_grant__status="active", user__is_active=True, user__access_status="active",
    ).select_related("device_grant")
    transient_failure = False
    for device in devices:
        try:
            token = device.get_token()
            data = {"feature": str(log.feature), "event": str(log.event),
                    "makerspace_id": str(log.makerspace_id)}
            if device.provider == PushDevice.Provider.FCM:
                if not settings_row.fcm_configured:
                    continue
                send_fcm(settings_row, token, "Space Works", log.text_body, data)
            else:
                if not settings_row.apns_configured:
                    continue
                from apps.integrations.push_apns import send_apns
                send_apns(settings_row, token, device.environment, "Space Works", log.text_body, data)
        except PushProviderError as exc:
            if exc.invalid_token:
                PushDevice.objects.filter(pk=device.pk).update(
                    active=False, invalidated_at=timezone.now()
                )
            else:
                transient_failure = True
            logger.warning("native_push_provider_failed", extra={
                "push_device_id": device.pk, "provider": device.provider,
                "invalid_token": exc.invalid_token,
            })
        except Exception:
            transient_failure = True
            logger.warning("native_push_delivery_failed", extra={
                "push_device_id": device.pk, "provider": device.provider,
            })
    if transient_failure:
        raise PushProviderError("Native push delivery failed.")
    return True
