"""F3 lifecycle mail addressed only to the membership's own account."""
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import notify_family, safe_adapter
from apps.makerspaces.platform import feature_enabled


@safe_adapter
def notify_term(term, event):
    membership = term.membership
    if not feature_enabled(membership.makerspace, "membership.lifecycle_mail"):
        return
    return notify_family(
        membership.makerspace, "members", event,
        bag(id=membership.pk, status=term.status),
        data={"membership_id": membership.pk, "term_id": term.pk},
        member_id=membership.user_id, requester_only=True,
    )


@safe_adapter
def notify_membership(membership, event):
    if feature_enabled(membership.makerspace, "membership.lifecycle_mail"):
        return notify_family(
            membership.makerspace, "members", event,
            bag(id=membership.pk, status=membership.status),
            data={"membership_id": membership.pk}, member_id=membership.user_id,
            requester_only=True,
        )
