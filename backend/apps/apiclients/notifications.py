"""API-access notices use the same matrix, module gates, quotas and logs as loans."""

from apps.apiclients.models import ApiKeyRequest
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle


def notify_api_key_request_resolved(api_key_request, *, sync=False):
    request_id = api_key_request.pk
    makerspace = api_key_request.makerspace

    def build():
        row = ApiKeyRequest.objects.select_related("requester").get(
            pk=request_id, makerspace=makerspace
        )
        subject = f"{makerspace.name} API access request {row.status}"
        body = f"Your API access request '{row.label}' for {makerspace.name} was {row.status}."
        if row.resolution_note:
            body = f"{body}\n\nNote: {row.resolution_note}"
        body = f"{body}\n\nNo API secret is included in this notification."
        emails = ()
        if row.requester and row.requester.email:
            emails = (EmailDelivery(
                to_email=row.requester.email,
                subject=subject,
                text_body=body,
                stream="api",
                mute_event="api_key_request_resolved",
                audience="requester",
                target="requester",
            ),)
        return LifecyclePayload(
            text=f"API access request #{row.pk} '{row.label}' was {row.status}.",
            emails=emails,
            data={"api_key_request_id": row.pk},
            staff_channels_enabled=makerspace.staff_notifications_enabled,
        )

    return notify_lifecycle(
        makerspace,
        feature="api_access",
        event="api_key_request_resolved",
        build=build,
        sync=sync,
    )
