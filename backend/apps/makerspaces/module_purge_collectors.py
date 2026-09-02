"""How each module's rows are actually removed (plan A9).

One function per module, called from `module_purge_plans.PLANS` inside the purge
transaction, after the caller has opened the transaction-scoped immutability bypass.
Splitting these out of the plan registry keeps "which plans exist" readable next to
"what each one deletes", and keeps both files inside the file-size ceiling.

Two rules every collector here obeys:

* **Only what this module owns.** The makerspace survives the purge and other modules
  stay installed, so a collector must not reach into their rows -- see
  `machine_service_delete`, which is deliberately narrower than the whole-tenant
  `machines.service_lifecycle.delete_for_makerspace`.
* **Model imports are function-local.** This module is imported by the plan registry,
  which the management command imports at load time; importing app models at module
  scope would drag half the app graph into every `manage.py` invocation.
"""

from apps.makerspaces.module_purge_collectors_machine_service import machine_service_delete
from apps.makerspaces.module_purge_collectors_single_model import (
    _counts,
    _delete,
    bookings_delete,
    bookings_public_images,
    machine_service_private_key_sizes,
    machine_service_private_keys,
    qr_print_batches_delete,
    stock_transfers_delete,
    stocktake_delete,
)


def events_delete(makerspace, cursor):
    from apps.events.models import (
        Event,
        EventAttendanceCertificate,
        EventCheckInEvent,
        EventCollaborator,
        EventFeedbackResponse,
        EventFeedbackSurvey,
        EventRegistration,
        EventSeries,
        EventSeriesCollaborator,
        MemberCalendarFeed,
    )

    feeds, feed_labels = _delete(
        MemberCalendarFeed.objects.filter(membership__makerspace=makerspace)
    )
    projected_collaborations, projected_collaboration_labels = _delete(
        EventCollaborator.objects.filter(
            source_series_collaboration__makerspace=makerspace
        ).exclude(event__makerspace=makerspace)
    )
    series_collaborations, series_collaboration_labels = _delete(
        EventSeriesCollaborator.objects.filter(makerspace=makerspace)
    )
    collaborations, collaboration_labels = _delete(
        EventCollaborator.objects.filter(makerspace=makerspace)
    )
    # Clearing activity provenance is the point. Payment routing is left intact in both places
    # holding it (`Payment.via_makerspace`, and the registration's `payment_via_makerspace` for
    # a charge raised later at promotion), so a receipt stays visible and a pending charge payable.
    provenance_cleared = EventRegistration.objects.filter(
        registered_via_makerspace=makerspace,
    ).exclude(event__makerspace=makerspace).update(registered_via_makerspace=None)
    certificates, certificate_labels = _delete(
        EventAttendanceCertificate.objects.filter(
            registration__event__makerspace=makerspace
        )
    )
    responses, response_labels = _delete(
        EventFeedbackResponse.objects.filter(survey__event__makerspace=makerspace)
    )
    surveys, survey_labels = _delete(
        EventFeedbackSurvey.objects.filter(event__makerspace=makerspace)
    )
    checkins, checkin_labels = _delete(
        EventCheckInEvent.objects.filter(registration__event__makerspace=makerspace)
    )
    registrations, registration_labels = _delete(
        EventRegistration.objects.filter(event__makerspace=makerspace)
    )
    events, event_labels = _delete(Event.objects.filter(makerspace=makerspace))
    series, series_labels = _delete(EventSeries.objects.filter(makerspace=makerspace))
    return _counts(
        model_labels=(
            collaboration_labels | certificate_labels | response_labels
            | survey_labels | checkin_labels | registration_labels | event_labels
            | projected_collaboration_labels | series_collaboration_labels | series_labels
            | feed_labels
        ),
        event_series_collaboration_projections=projected_collaborations,
        event_series_collaborations=series_collaborations,
        event_collaborations=collaborations,
        event_certificates=certificates,
        event_feedback_responses=responses,
        event_feedback_surveys=surveys,
        event_check_in_events=checkins,
        event_registration_provenance_cleared=provenance_cleared,
        event_registrations=registrations,
        events=events,
        event_series=series,
        event_calendar_feeds=feeds,
    )


def events_public_images(makerspace):
    from apps.events.models import Event, EventSeries

    return [
        *Event.objects.filter(makerspace=makerspace).values_list("image_key", flat=True),
        *EventSeries.objects.filter(makerspace=makerspace).values_list("image_key", flat=True),
    ]


def events_private_keys(makerspace, add):
    from apps.events.models import EventAttendanceCertificate

    for key in EventAttendanceCertificate.objects.filter(
        registration__event__makerspace=makerspace
    ).values_list("object_key", flat=True):
        add(key)


def events_private_key_sizes(makerspace):
    from apps.events.models import EventAttendanceCertificate

    return {
        key: size
        for key, size in EventAttendanceCertificate.objects.filter(
            registration__event__makerspace=makerspace
        ).values_list("object_key", "size_bytes")
        if key
    }


def maintenance_delete(makerspace, cursor):
    from apps.maintenance.models import (
        MaintenanceLog,
        MaintenanceLogDocument,
        MaintenanceSchedule,
    )
    documents, document_labels = _delete(
        MaintenanceLogDocument.objects.filter(log__machine__makerspace=makerspace)
    )
    logs, log_labels = _delete(
        MaintenanceLog.objects.filter(machine__makerspace=makerspace)
    )
    schedules, schedule_labels = _delete(
        MaintenanceSchedule.objects.filter(machine__makerspace=makerspace)
    )
    return _counts(
        model_labels=document_labels | log_labels | schedule_labels,
        documents=documents,
        logs=logs,
        schedules=schedules,
    )


def maintenance_private_keys(makerspace, add):
    from apps.maintenance.models import MaintenanceLogDocument

    for key in MaintenanceLogDocument.objects.filter(
        log__machine__makerspace=makerspace
    ).values_list("object_key", flat=True):
        add(key)


def maintenance_private_key_sizes(makerspace):
    """Charged bytes per document key, for release after a confirmed object delete.

    `services_documents.upload_log_document` charges `limits.add_storage`, so purging the
    module must give those bytes back -- but only for objects the bucket confirms are
    gone. Freeing them alongside the row deletion looked safe because the size comes from
    a column rather than an S3 HEAD, and it is not: the rows commit, the best-effort
    object delete can then fail, and the makerspace ends up holding storage it is no
    longer charged for.
    """
    from apps.maintenance.models import MaintenanceLogDocument

    return {
        key: size
        for key, size in MaintenanceLogDocument.objects.filter(
            log__machine__makerspace=makerspace
        ).values_list("object_key", "size_bytes")
        if key
    }


def procurement_delete(makerspace, cursor):
    from apps.procurement.models import ToBuyItem, ToBuyReceipt

    receipts, receipt_labels = _delete(
        ToBuyReceipt.objects.filter(to_buy_item__makerspace=makerspace)
    )
    items, item_labels = _delete(ToBuyItem.objects.filter(makerspace=makerspace))
    return _counts(
        model_labels=receipt_labels | item_labels,
        receipts=receipts,
        to_buy_items=items,
    )


def procurement_private_keys(makerspace, add):
    from apps.procurement.models import ToBuyReceipt

    for key in ToBuyReceipt.objects.filter(
        to_buy_item__makerspace=makerspace
    ).values_list("object_key", flat=True):
        add(key)


def notifications_delete(makerspace, cursor):
    from apps.notifications.models import Notification

    deleted, labels = _delete(Notification.objects.filter(makerspace=makerspace))
    return _counts(model_labels=labels, notifications=deleted)


def _chat_destinations_delete(makerspace, channel):
    """Delete one chat channel's rooms and their stored credentials.

    This was not needed while a channel's credential was a column on `Makerspace` — the
    channel owned no rows at all. A destination holds an encrypted webhook URL or chat id,
    so purging `discord` after uninstalling it must destroy those secrets, not leave them
    readable in a table nothing surfaces any more. The scope link tables and the delivery
    logs' `destination` FK both fall out of this by CASCADE and SET_NULL respectively:
    history survives, the credential does not.
    """
    from apps.integrations.models_destinations import NotificationDestination

    deleted, labels = _delete(
        NotificationDestination.objects.filter(makerspace=makerspace, channel=channel)
    )
    return _counts(model_labels=labels, destinations=deleted)


def telegram_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "telegram")


def slack_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "slack")


def mattermost_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "mattermost")


def discord_destinations_delete(makerspace, cursor):
    return _chat_destinations_delete(makerspace, "discord")


def membership_public_image_keys(makerspace):
    """Avatars and project images, collected BEFORE the rows that name them go.

    Without this the objects outlive every row that could name them: nothing else in the
    system knows a `member/<id>/...` key exists once the profile is deleted, so they
    would sit in the bucket forever and keep counting against the space's storage.
    """
    from apps.makerspaces.models import MemberProfile, MemberProject

    keys = list(
        MemberProfile.objects.filter(membership__makerspace=makerspace).values_list(
            "avatar_key", flat=True
        )
    )
    keys += list(
        MemberProject.objects.filter(
            profile__membership__makerspace=makerspace
        ).values_list("image_key", flat=True)
    )
    return [key for key in dict.fromkeys(keys) if key]


def membership_delete(makerspace, cursor):
    from apps.makerspaces.models import MemberProfile, MembershipRequest

    # `MakerspaceMembership` itself is core RBAC state and is NEVER deleted here -- the
    # module gates community enrolment/content, not the roster (plan A7). Waivers and
    # both acceptance evidence types are core liability records and likewise survive.
    # Profiles go even though the membership stays: a profile is community content the
    # module owns, not the RBAC state the module deliberately leaves behind. Projects
    # cascade from the profile.
    profiles, profile_labels = _delete(
        MemberProfile.objects.filter(membership__makerspace=makerspace)
    )
    requests, request_labels = _delete(
        MembershipRequest.objects.filter(makerspace=makerspace)
    )
    return _counts(
        model_labels=profile_labels | request_labels,
        member_profiles=profiles,
        membership_requests=requests,
    )
