"""Additional membership lifecycle events under the stable `members` feature."""

from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import bounded, notify_family, safe_adapter


@safe_adapter
def notify_membership_decision(row, event):
    status = getattr(row, "state", getattr(row, "status", ""))
    is_request = hasattr(row, "state")
    return notify_family(
        row.makerspace, "members", event, bag(id=row.pk, status=bounded(status)),
        data={"membership_request_id" if is_request else "membership_id": row.pk},
        # Approval already sends a member welcome email independently of this matrix.
        member_id=None if event == "approved" else row.user_id,
    )
