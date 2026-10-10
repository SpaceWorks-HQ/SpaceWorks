"""F3 membership-family notices addressed only to the authenticated applicant."""
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import notify_family, safe_adapter


@safe_adapter
def notify_admission(row, event):
    return notify_family(
        row.makerspace, "members", event, bag(id=row.pk, status=row.state),
        data={"membership_request_id": row.pk}, member_id=row.user_id, admission_request_id=row.pk,
    )
