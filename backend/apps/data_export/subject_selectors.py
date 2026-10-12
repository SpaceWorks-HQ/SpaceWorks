"""Subject ownership, layered over the reviewed tenant dataset registry.

These are row selectors, never a second column allowlist. Authorship is deliberately
not ownership: a staff member who handles somebody's loan cannot export that loan.
Unlisted tenant configuration and anonymous records have no proven subject binding.
"""

from django.db.models import Q

from apps.accounts import rbac

from .datasets import DATASET_SPECS


SUBJECT_PATHS = {
    "operations.SavedView": ("owner",),
    "apiclients.ApiKeyRequest": ("requester",),
    "bookings.Booking": ("member",),
    "devices.PrinterJob": ("service_request__member",),
    "devices.PrinterJobConsumption": ("job__service_request__member",),
    "boxes.BoxScan": ("request__requester",),
    "boxes.QrScanEvent": ("request__requester",),
    "events.EventRegistration": ("member",),
    "events.EventCheckInEvent": ("registration__member",),
    "events.EventFeedbackResponse": ("registration__member",),
    "events.EventAttendanceCertificate": ("registration__member",),
    "evidence.EvidencePhoto": ("uploaded_by",),
    "evidence.EvidenceObjectRetentionState": ("evidence__uploaded_by",),
    "hardware_requests.HardwareRequest": ("requester",),
    "hardware_requests.HardwareRequestItem": ("request__requester",),
    "hardware_requests.HardwareRequestItemAsset": ("request_item__request__requester",),
    "hardware_requests.PublicProblemReport": ("requester",),
    "hardware_requests.PublicToolLoan": ("requester",),
    "hardware_requests.RequesterAccountability": ("requester",),
    "hardware_requests.ReturnEvent": ("request__requester",),
    "integrations.NotificationRecipient": ("user",),
    "machines.MachineOperator": ("user",),
    "machines.MachineServiceRequest": ("member",),
    "machines.MachineUsageEntry": ("service_request__member",),
    "machines.CertificationGrant": ("membership__user",),
    "machines.ServiceRequestFile": ("owner_user",),
    "machines.ServiceRequestConsumption": ("service_request__member",),
    "makerspaces.MakerspaceMembership": ("user",),
    "makerspaces.MemberCard": ("membership__user",),
    "makerspaces.MemberProfile": ("membership__user",),
    "makerspaces.MemberProject": ("profile__membership__user",),
    "makerspaces.MembershipRequest": ("user",),
    "makerspaces.MembershipVouch": ("request__user",),
    "makerspaces.MembershipTerm": ("membership__user",),
    "payments.Payment": ("member",),
    "payments.ManualSettlement": ("payment__member",),
    "payments.Refund": ("payment__member",),
    "presence.PresenceSession": ("member",),
}


def subject_query(model, user, makerspace_id):
    label = model._meta.label
    if label == "accounts.User":
        return model.objects.filter(pk=user.pk)
    if label == "audit.AuditLog":
        own = Q(actor_id=user.pk) | Q(
            target_type="accounts.user", target_id=str(user.pk),
        )
        memberships = rbac.scope_by_makerspace(
            user, user.makerspace_memberships.all(),
        ).filter(makerspace_id=makerspace_id)
        own |= Q(
            target_type="makerspaces.makerspacemembership",
            target_id__in=[str(pk) for pk in memberships.values_list("pk", flat=True)],
        )
    else:
        paths = SUBJECT_PATHS.get(label)
        if not paths:
            return model.objects.none()
        own = Q()
        for path in paths:
            own |= Q(**{f"{path}_id": user.pk})
    predicate = DATASET_SPECS[label][1]
    query = model.objects.filter(own).filter(predicate.as_q(makerspace_id))
    # An explicit tenant intersection remains required even for a superadmin.
    return rbac.scope_by_makerspace(queryset=query, actor=user,
                                   makerspace_field=predicate.any_paths[0] + "_id")
