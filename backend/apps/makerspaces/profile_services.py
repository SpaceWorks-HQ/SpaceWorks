"""Reading and writing a member's own profile, and the member-visible directory."""

from django.db import transaction

from apps.audit import services as audit
from apps.inventory import public_image_storage
from apps.makerspaces.models import MakerspaceMembership, MemberProfile, MemberProject

RECENT_ATTENDED_EVENTS_LIMIT = 20


def profile_for(membership):
    """The membership's profile row, created on demand.

    Created rather than returned as defaults so every later write has a row to lock and
    a stable id to hang project rows and image keys off. It is empty and invisible, so
    creating one publishes nothing.
    """
    profile, _ = MemberProfile.objects.get_or_create(membership=membership)
    return profile


def display_name_for(membership):
    user = membership.user
    return user.display_name or user.get_full_name().strip() or user.username


def read_profile(membership, *, include_activity=True):
    profile = profile_for(membership)
    payload = {
        "membership_id": membership.pk,
        "display_name": display_name_for(membership),
        "is_visible": profile.is_visible,
        "show_attended_events": profile.show_attended_events,
        "headline": profile.headline,
        "institution": profile.institution,
        "bio": profile.bio,
        "avatar_url": public_image_storage.public_url(profile.avatar_key) or None,
        "interests": profile.interests or [],
        "languages": profile.languages or [],
        "education": profile.education or [],
        "github_username": profile.github_username,
        "github_contributions": profile.github_contributions,
        "projects": [
            {
                "id": project.pk,
                "title": project.title,
                "description": project.description,
                "links": project.links or [],
                "image_url": public_image_storage.public_url(project.image_key) or None,
            }
            for project in profile.projects.all()
        ],
        "activity": profile_activity(membership) if include_activity else {},
    }
    return payload


def profile_activity(membership):
    """Counts of what this member has done in THIS space.

    Derived, never stored: a stored counter drifts the moment a registration is
    cancelled. Each section is omitted when its module is off rather than reported as
    zero -- a zero says "attended nothing", an absent key says "this space does not run
    events", and they are not the same statement.
    """
    from apps.makerspaces.platform import module_enabled

    activity = {}
    makerspace = membership.makerspace
    if module_enabled(makerspace, "events"):
        from apps.events.member_history import registrations_for_space
        from apps.events.models import EventRegistration

        registrations = registrations_for_space(makerspace, membership.user)
        activity["events_attended"] = registrations.filter(
            status=EventRegistration.Status.ATTENDED
        ).count()
        # Cancellations are excluded: "registered for 40 events" is not a truthful
        # summary of someone who cancelled thirty of them.
        activity["events_registered"] = registrations.exclude(
            status=EventRegistration.Status.CANCELLED
        ).count()
        # Read the consent flag straight from the row, deliberately NOT through
        # `membership.profile` or `profile_for`. `get_or_create(membership=...)` populates
        # the reverse one-to-one cache on the membership instance, and `save_profile`
        # re-reads the row through a *separate* instance -- so anything saving twice on one
        # membership object would then gate publication on a stale copy of the flag. A
        # privacy gate must not depend on which instance happened to warm a cache. This
        # also stops a read path from creating a row, which `profile_for` would.
        show_attended_events = MemberProfile.objects.filter(
            membership=membership
        ).values_list("show_attended_events", flat=True).first()
        if show_attended_events:
            recent = (
                registrations.filter(status=EventRegistration.Status.ATTENDED)
                .select_related("event")
                .only("event__id", "event__title", "event__starts_at")
                # `-id` is a tiebreaker, not decoration: two events can share a
                # `starts_at`, and without it the cap could include a different subset
                # on each request. `member_activity_service` orders the same way.
                .order_by("-event__starts_at", "-id")[:RECENT_ATTENDED_EVENTS_LIMIT]
            )
            activity["recent_attended_events"] = [
                {
                    "id": registration.event.id,
                    "title": registration.event.title,
                    "starts_at": registration.event.starts_at,
                }
                for registration in recent
            ]
    return activity


@transaction.atomic
def save_profile(membership, data):
    """Apply a partial profile update, replacing the project list when one is sent."""
    profile = MemberProfile.objects.select_for_update().filter(
        membership=membership
    ).first() or profile_for(membership)
    was_visible = profile.is_visible
    attended_events_were_shown = profile.show_attended_events
    project_count_before = profile.projects.count()
    fields = []
    for field in (
        "is_visible", "show_attended_events", "headline", "institution", "bio",
        "interests", "languages", "education",
    ):
        if field in data:
            setattr(profile, field, data[field])
            fields.append(field)
    if "github_username" in data:
        username = (data["github_username"] or "").strip()
        if username != profile.github_username:
            # A new handle invalidates the cached count outright rather than leaving the
            # previous account's total showing under someone else's name until the next
            # sync — which would be a false claim, not merely stale data.
            profile.github_username = username
            profile.github_contributions = None
            profile.github_synced_at = None
            fields += ["github_username", "github_contributions", "github_synced_at"]
    if fields:
        profile.save(update_fields=[*fields, "updated_at"])
    if "projects" in data:
        save_projects(profile, data["projects"])
    _audit_profile_saved(
        membership,
        profile,
        was_visible,
        attended_events_were_shown,
        project_count_before,
        fields,
    )
    return profile


def _audit_profile_saved(
    membership,
    profile,
    was_visible,
    attended_events_were_shown,
    project_count_before,
    fields,
):
    """Record that the profile changed, without copying its contents into the log.

    The audit log is append-only and makerspace-scoped, so it must say *what changed*
    and by whom — but writing profile contents or derived event details into it would
    copy member PII into a store that is deliberately impossible to edit or delete. The
    meta therefore names the fields touched and the boolean publication transitions.
    """
    profile.refresh_from_db(fields=["is_visible", "show_attended_events"])
    audit.record(
        membership.user,
        "member.profile_updated",
        makerspace=membership.makerspace,
        target=membership,
        meta={
            "fields": sorted(fields),
            "visibility_changed": was_visible != profile.is_visible,
            "is_visible": profile.is_visible,
            "attended_events_shown": profile.show_attended_events,
            "attended_events_changed": (
                attended_events_were_shown != profile.show_attended_events
            ),
            "projects_before": project_count_before,
            "projects_after": profile.projects.count(),
        },
    )


def save_projects(profile, rows):
    """Replace the project list.

    Replace rather than merge, matching every other list-shaped save in this codebase
    (role scopes, notification recipients, chat rooms): with a merge there is no way to
    express deleting one, so the member could add projects forever and remove none.

    An id the caller does not own is a **400, not a silent drop** — a save that quietly
    discards part of the submission leaves the member believing it was stored.
    """
    from rest_framework.exceptions import ValidationError

    existing = {project.pk: project for project in profile.projects.all()}
    seen = set()
    for position, row in enumerate(rows):
        project_id = row.get("id")
        if project_id is not None:
            project = existing.get(project_id)
            if project is None:
                raise ValidationError({"projects": f"Unknown project id {project_id}."})
            project.title = row["title"]
            project.description = row.get("description", "")
            project.links = row.get("links", [])
            project.position = position
            project.save(
                update_fields=["title", "description", "links", "position", "updated_at"]
            )
            seen.add(project_id)
            continue
        MemberProject.objects.create(
            profile=profile,
            title=row["title"],
            description=row.get("description", ""),
            links=row.get("links", []),
            position=position,
        )
    removed = [project for pk, project in existing.items() if pk not in seen]
    for project in removed:
        # Freed and deleted through the image service so the storage counter and the
        # bucket stay in step with the row disappearing.
        from apps.makerspaces import profile_images

        profile_images.clear_project_image(profile, project)
    MemberProject.objects.filter(
        pk__in=[project.pk for project in removed]
    ).delete()


def directory(makerspace):
    """Visible profiles, plus a count of everyone who did not opt in."""
    memberships = MakerspaceMembership.objects.filter(
        makerspace=makerspace, status="active", user__is_active=True
    ).select_related("user", "profile")
    members, hidden = [], 0
    for membership in memberships:
        profile = getattr(membership, "profile", None)
        # No profile row at all is the same answer as one that is not visible: nobody
        # is listed until they choose to be.
        if profile is None or not profile.is_visible:
            hidden += 1
            continue
        members.append(
            {
                "membership_id": membership.pk,
                "display_name": display_name_for(membership),
                "headline": profile.headline,
                "avatar_url": public_image_storage.public_url(profile.avatar_key) or None,
            }
        )
    members.sort(key=lambda row: row["display_name"].lower())
    return {"members": members, "hidden_count": hidden}


def visible_profile(makerspace, membership_id):
    """One other member's profile, or None when it is not theirs to see."""
    membership = MakerspaceMembership.objects.select_related("user", "profile").filter(
        pk=membership_id, makerspace=makerspace, status="active", user__is_active=True
    ).first()
    if membership is None:
        return None
    profile = getattr(membership, "profile", None)
    if profile is None or not profile.is_visible:
        return None
    return read_profile(membership)
