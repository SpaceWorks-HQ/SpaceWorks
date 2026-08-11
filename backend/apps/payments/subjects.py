"""Resolve payment subjects snapshot-first, then by owner-checked live lookup.

Snapshots preserve the title charged at creation even when live event and space names are
edited; the generic subject display is the final fallback after a purge or ownership mismatch.
"""

from apps.payments.models import Payment


def resolve_subject_labels(payments):
    rows = list(payments)
    labels = {}
    by_type = {
        subject_type: {
            payment.subject_id
            for payment in rows
            if payment.subject_type == subject_type
        }
        for subject_type in Payment.SubjectType.values
    }

    if ids := by_type[Payment.SubjectType.MACHINE_SERVICE_REQUEST]:
        from apps.machines.models import MachineServiceRequest

        for subject_id, title, makerspace_id in MachineServiceRequest.objects.filter(
            pk__in=ids
        ).values_list("pk", "title", "makerspace_id"):
            labels[(Payment.SubjectType.MACHINE_SERVICE_REQUEST, subject_id)] = (
                title,
                makerspace_id,
                None,
            )
    if ids := by_type[Payment.SubjectType.BOOKING]:
        from apps.bookings.models import Booking

        for subject_id, name, makerspace_id in Booking.objects.filter(
            pk__in=ids
        ).values_list("pk", "space__name", "space__makerspace_id"):
            labels[(Payment.SubjectType.BOOKING, subject_id)] = (
                name,
                makerspace_id,
                None,
            )
    if ids := by_type[Payment.SubjectType.EVENT_REGISTRATION]:
        from apps.events.models import EventRegistration

        for (
            subject_id,
            title,
            makerspace_id,
            member_id,
        ) in EventRegistration.objects.filter(pk__in=ids).values_list(
            "pk", "event__title", "event__makerspace_id", "member_id"
        ):
            labels[(Payment.SubjectType.EVENT_REGISTRATION, subject_id)] = (
                title,
                makerspace_id,
                member_id,
            )
    for payment in rows:
        if payment.subject_type != Payment.SubjectType.MAKERSPACE_MEMBERSHIP:
            continue
        labels[(payment.subject_type, payment.subject_id)] = (
            "Membership dues",
            payment.makerspace_id,
            None,
        )
    return labels


def subject_label(payment, labels):
    if payment.subject_label:
        return payment.subject_label
    resolved = labels.get((payment.subject_type, payment.subject_id))
    if resolved is not None:
        label, makerspace_id, member_id = resolved
        if (
            label
            and makerspace_id == payment.makerspace_id
            and (member_id is None or member_id == payment.member_id)
        ):
            return label
    return payment.get_subject_type_display() or "Payment"
