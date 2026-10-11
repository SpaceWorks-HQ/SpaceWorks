"""Personal channel opt-outs cannot turn a tenant channel on."""

from django.apps import apps

from apps.accounts import rbac
from apps.integrations.notification_catalog import FEATURE_EVENTS, is_notification_enabled
from apps.integrations.notification_rules import ALWAYS_ON
from apps.makerspaces.platform import feature_enabled, module_enabled

PERSONAL_CHANNELS = ("email", "in_app", "native_push")
STREAM_FEATURES = {"hardware": "hardware_requests", "membership": "members", "api": "api_access"}


def mandatory_email(stream, event):
    from apps.integrations.dispatch import EMAIL_MODULE_EXEMPT

    return (stream, event) in EMAIL_MODULE_EXEMPT or event in ALWAYS_ON or (
        stream == "hardware" and event == "closed_with_issue"
    )


def personal_enabled(makerspace, user_id, feature, channel, *, stream="", event=""):
    if channel == "email" and mandatory_email(stream, event):
        return True
    if not user_id:
        return True
    model = apps.get_model("notifications", "MemberNotificationPreference")
    # Stored opt-outs remain honoured even if the preference editor is later disabled.
    return not rbac.scope_notification_policy(model.objects.all(), makerspace_id=makerspace.pk).filter(
        user_id=user_id, feature=feature, channel=channel, enabled=False,
    ).exists()


def channel_available(makerspace, feature, channel):
    from apps.integrations.recipients import feature_available

    if not feature_available(makerspace, feature):
        return False
    if not is_notification_enabled(makerspace, feature, channel):
        return False
    if channel == "email":
        return module_enabled(makerspace, "email")
    if channel == "in_app":
        return feature_enabled(makerspace, "notifications.member_inbox")
    return feature_enabled(makerspace, "mobile.push")


def preference_cells(makerspace, user):
    model = apps.get_model("notifications", "MemberNotificationPreference")
    saved = {(row.feature, row.channel): row for row in rbac.scope_personal_notifications(
        user, model.objects.all(),
    ).filter(makerspace=makerspace)}
    from apps.integrations.recipients import feature_available

    return [{
        "feature": feature, "channel": channel,
        "enabled": saved[(feature, channel)].enabled if (feature, channel) in saved else True,
        "daily_digest": saved[(feature, channel)].daily_digest if (feature, channel) in saved else False,
        "available": channel_available(makerspace, feature, channel),
        "mandatory_events": [event for event in events if channel == "email" and mandatory_email(
            "hardware" if feature == "hardware_requests" else "membership" if feature == "members" else feature,
            event,
        )],
    } for feature, events in FEATURE_EVENTS.items() if feature_available(makerspace, feature)
       for channel in PERSONAL_CHANNELS]
