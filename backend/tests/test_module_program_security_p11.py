"""Phase 11 -- the security pass over the module-architecture program.

Every check here corresponds to a finding or an accepted risk in
`docs/module-program-security-report.md`. They are written as assertions rather than
prose because a boundary nobody tests is a boundary that quietly moves.
"""

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import (
    PasswordResetEnvelopeStatus,
    PlatformLoginMethods,
    User,
)
from apps.accounts.services_password_reset_drain import (
    claim_pending_envelopes,
    prepare_delivery,
)
from apps.inventory.public_image_storage import build_object_key
from apps.makerspaces import profile_services
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MemberProfile,
)
from apps.makerspaces.walk_in_services import create_walk_in_member

pytestmark = pytest.mark.django_db

PASSWORD = "Safe audit password 947!"


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def staffer(makerspace, slug="inventory_manager", username="auditor"):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        password=PASSWORD,
        access_status=User.AccessStatus.ACTIVE,
    )
    role = MakerspaceRole.objects.get(makerspace=makerspace, slug=slug)
    MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=role.legacy_role or MakerspaceMembership.Role.CUSTOM,
        assigned_role=role, status="active",
    )
    return user


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- walk-in records ---------------------------------------------------------------


def test_a_walk_in_record_grants_no_authority_anywhere():
    """It names a person. It must not be a way to manufacture access."""
    space = make_space("walkin-authority")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    assert membership.assigned_role.granted_actions == []
    for action in (
        rbac.Action.ISSUE_DIRECT_LOAN, rbac.Action.EDIT_INVENTORY,
        rbac.Action.MANAGE_MAKERSPACE, rbac.Action.VIEW_AUDIT,
    ):
        assert rbac.can(membership.user, action, space.pk) is False
    assert membership.user.is_staff is False
    assert membership.user.is_superuser is False
    assert membership.user.role == User.Role.REQUESTER


def test_a_walk_in_record_cannot_be_signed_into():
    space = make_space("walkin-login")
    front_desk = staffer(space)
    membership = create_walk_in_member(
        front_desk, space, display_name="Walk In", email="walkin@example.test"
    )

    assert membership.user.has_usable_password() is False
    # Not merely "no password set" — the login endpoint must actually refuse. An empty
    # string, a blank body and the unusable-password marker must all fail.
    client = APIClient()
    for attempt in ("", " ", "!"):
        response = client.post(
            "/api/v1/auth/login",
            {"username": membership.user.username, "password": attempt},
            format="json",
        )
        # 400 for a blank credential, 401 for a wrong one — the property under test is
        # that no input signs this record in.
        assert response.status_code in (400, 401), attempt


def test_a_walk_in_is_confined_to_the_makerspace_that_created_it():
    space = make_space("walkin-scope-a")
    other = make_space("walkin-scope-b")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    assert not MakerspaceMembership.objects.filter(
        user=membership.user, makerspace=other
    ).exists()
    assert rbac.makerspaces_for_action(
        membership.user, rbac.Action.VIEW_INVENTORY
    ) in (set(), frozenset())


def test_walk_in_creation_is_charged_against_the_member_quota():
    """Otherwise the front desk is an unmetered way past a managed plan's limits."""
    from apps.makerspaces import limits

    space = make_space("walkin-quota")
    front_desk = staffer(space)
    calls = []
    original = limits.check_quota

    def spy(makerspace, key, *, adding=1):
        calls.append(key)
        return original(makerspace, key, adding=adding)

    limits.check_quota = spy
    try:
        create_walk_in_member(front_desk, space, display_name="Walk In")
    finally:
        limits.check_quota = original
    assert "members" in calls


# --- maker profiles ----------------------------------------------------------------


def member_of(makerspace, username):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        phone="+15550100100",
        display_name=username.title(),
        access_status=User.AccessStatus.ACTIVE,
    )
    return MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
        status="active",
    )


def test_a_profile_image_key_from_another_makerspace_is_refused():
    """The prefix check is what stops one tenant attaching another tenant's object."""
    space = make_space("image-scope-a")
    other = make_space("image-scope-b")
    membership = member_of(space, "owner")
    foreign_key = build_object_key("member", other.pk, ".png")

    response = authed(membership.user).put(
        f"/api/v1/member/makerspaces/{space.pk}/profile/image",
        {"object_key": foreign_key},
        format="json",
    )
    assert response.status_code == 400
    assert "object_key" in response.data


def test_a_member_cannot_edit_another_members_project():
    space = make_space("project-owner")
    mine = member_of(space, "mine")
    theirs = member_of(space, "theirs")
    their_profile = profile_services.profile_for(theirs)
    profile_services.save_projects(their_profile, [{"title": "Theirs"}])
    their_project = their_profile.projects.get()

    response = authed(mine.user).put(
        f"/api/v1/member/makerspaces/{space.pk}/profile",
        {"projects": [{"id": their_project.pk, "title": "Hijacked"}]},
        format="json",
    )
    assert response.status_code == 400
    their_project.refresh_from_db()
    assert their_project.title == "Theirs"


def test_publishing_a_profile_never_publishes_contact_details():
    space = make_space("profile-pii")
    subject = member_of(space, "subject")
    viewer = member_of(space, "viewer")
    profile_services.save_profile(subject, {"is_visible": True, "bio": "Hello"})

    payload = authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory/{subject.pk}"
    ).data
    serialized = str(payload)
    assert subject.user.email not in serialized
    assert subject.user.phone not in serialized


def test_a_member_of_another_space_cannot_read_this_directory():
    space = make_space("directory-a")
    other = make_space("directory-b")
    subject = member_of(space, "subject")
    outsider = member_of(other, "outsider")
    profile_services.save_profile(subject, {"is_visible": True})

    assert authed(outsider.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory"
    ).status_code == 403
    assert authed(outsider.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory/{subject.pk}"
    ).status_code == 403


def test_a_revoked_member_disappears_from_the_directory():
    space = make_space("directory-revoked")
    subject = member_of(space, "subject")
    viewer = member_of(space, "viewer")
    profile_services.save_profile(subject, {"is_visible": True})
    assert authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory"
    ).data["members"]

    subject.status = "revoked"
    subject.save(update_fields=["status"])

    listing = authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory"
    ).data
    assert listing["members"] == []
    # And not merely hidden from the list — the detail route closes too.
    assert authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory/{subject.pk}"
    ).status_code == 404


def test_a_suspended_account_cannot_reach_its_own_profile():
    space = make_space("profile-suspended")
    membership = member_of(space, "suspended")
    membership.user.access_status = User.AccessStatus.RESTRICTED
    membership.user.save(update_fields=["access_status"])

    assert authed(membership.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/profile"
    ).status_code == 403


def test_profile_links_reject_every_scheme_but_http():
    space = make_space("profile-schemes")
    membership = member_of(space, "author")
    client = authed(membership.user)

    for url in ("javascript:alert(1)", "data:text/html,<script>", "vbscript:x", "file:///etc/passwd"):
        response = client.put(
            f"/api/v1/member/makerspaces/{space.pk}/profile",
            {"projects": [{"title": "X", "links": [{"label": "Go", "url": url}]}]},
            format="json",
        )
        assert response.status_code == 400, url


# --- login-method switches ---------------------------------------------------------


def test_disabling_passwords_does_not_revoke_a_live_session():
    """Documented, accepted behaviour: a switch is a policy change, not a revocation."""
    space = make_space("session-survival")
    user = staffer(space)
    client = APIClient()
    signed_in = client.post(
        "/api/v1/auth/login", {"username": user.username, "password": PASSWORD}, format="json"
    )
    assert signed_in.status_code == 200

    PlatformLoginMethods.objects.update_or_create(
        pk=1,
        defaults={
            "password_enabled": False, "social_enabled": True,
            "phone_enabled": True, "self_registration_enabled": True,
        },
    )
    # New sign-ins are refused...
    assert client.post(
        "/api/v1/auth/login", {"username": user.username, "password": PASSWORD}, format="json"
    ).status_code == 403
    # ...while the token already issued keeps working. Revoking sessions is the
    # restrict/suspend flow's job, not a login-method switch's.
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in.data['access']}")
    assert client.get("/api/v1/auth/me").status_code == 200


def test_the_switch_row_is_never_written_by_an_anonymous_request():
    """A read path that writes is a write per unauthenticated login attempt."""
    APIClient().get("/api/v1/config")
    APIClient().post(
        "/api/v1/auth/login", {"username": "nobody", "password": "x"}, format="json"
    )
    assert not PlatformLoginMethods.objects.exists()


# --- module gating -----------------------------------------------------------------


def test_uninstalling_membership_closes_the_profile_surfaces_but_keeps_the_data():
    from apps.makerspaces.module_install import uninstall_module

    space = make_space("profile-uninstall")
    membership = member_of(space, "author")
    profile_services.save_profile(membership, {"is_visible": True, "bio": "Kept"})
    uninstall_module(space, "membership")

    client = authed(membership.user)
    assert client.get(f"/api/v1/member/makerspaces/{space.pk}/profile").status_code == 400
    assert client.get(f"/api/v1/member/makerspaces/{space.pk}/directory").status_code == 400
    # Uninstall hides; only a purge destroys.
    assert MemberProfile.objects.get(membership=membership).bio == "Kept"


# --- fixes from the Codex Stage-4 review -------------------------------------------


def disable_passwords():
    PlatformLoginMethods.objects.update_or_create(
        pk=1,
        defaults={
            "password_enabled": False, "social_enabled": True,
            "phone_enabled": True, "self_registration_enabled": True,
        },
    )


def test_the_control_plane_keeps_its_password_door_by_default():
    """The round-1 fix closed a real hole and created a permanent lockout.

    `/control/login/` is Django's AdminSite login, not the JWT one, so gating only the
    API left a password door on the control plane. Refusing it unconditionally was
    worse: social sign-in mints JWTs for the React console and never a Django session,
    so with `password_enabled=False` there was no route back to the one page that can
    re-enable it, and the deployment was sealed the moment the last admin session
    expired. The switch governs the application surfaces; `/control/` stays reachable.
    """
    User.objects.create_superuser(
        username="root", email="root@example.test", password=PASSWORD
    )
    disable_passwords()

    signed_in = APIClient().post(
        "/control/login/", {"username": "root", "password": PASSWORD}
    )
    assert signed_in.status_code in (200, 302)
    assert "_auth_user_id" in signed_in.client.session, (
        "the superadmin must keep a way back into the console that owns the switch"
    )


def test_the_control_plane_login_is_refused_once_another_route_exists(settings):
    """The enforcement is real -- it is conditional on a survivable alternative."""
    settings.PLATFORM_ADMIN_SSO = True
    User.objects.create_superuser(
        username="root", email="root@example.test", password=PASSWORD
    )
    assert APIClient().post(
        "/control/login/", {"username": "root", "password": PASSWORD}
    ).status_code in (200, 302)

    disable_passwords()
    refused = APIClient().post(
        "/control/login/", {"username": "root", "password": PASSWORD}
    )
    # Refused before the form authenticates, so no session is minted at all.
    assert refused.status_code == 403
    assert "_auth_user_id" not in refused.client.session


def test_a_malformed_project_id_does_not_delete_the_avatar():
    space = make_space("image-malformed")
    membership = member_of(space, "owner")
    profile = profile_services.profile_for(membership)
    MemberProfile.objects.filter(pk=profile.pk).update(
        avatar_key=build_object_key("member", space.pk, ".png")
    )

    response = authed(membership.user).delete(
        f"/api/v1/member/makerspaces/{space.pk}/profile/image?project_id=abc"
    )
    assert response.status_code == 400
    profile.refresh_from_db()
    assert profile.avatar_key, "the avatar must survive a malformed project id"


def test_a_restricted_member_cannot_be_registered_for_an_event():
    from datetime import timedelta

    from django.utils import timezone

    from apps.events.models import Event, EventRegistration

    space = make_space("event-restricted")
    manager_user = staffer(space, slug="space_manager", username="events-manager")
    membership = member_of(space, "restricted")
    membership.user.access_status = User.AccessStatus.RESTRICTED
    membership.user.save(update_fields=["access_status"])
    now = timezone.now()
    event = Event.objects.create(
        makerspace=space, title="Night", starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=2), is_public=True, status=Event.Status.PUBLISHED,
    )
    client = authed(manager_user)

    assert client.post(
        f"/api/v1/admin/events/{event.pk}/registrations/",
        {"member_id": membership.user_id}, format="json",
    ).status_code == 404
    assert not EventRegistration.objects.exists()
    # And the picker must not offer them either.
    listed = client.get(f"/api/v1/admin/events/{event.pk}/eligible-members/").data
    assert membership.user_id not in [row["member_id"] for row in listed]


def test_profile_mutations_are_audited_without_copying_the_content():
    from apps.audit.models import AuditLog

    space = make_space("profile-audit")
    membership = member_of(space, "author")
    authed(membership.user).put(
        f"/api/v1/member/makerspaces/{space.pk}/profile",
        {"is_visible": True, "bio": "a private sentence"},
        format="json",
    )

    entry = AuditLog.objects.filter(action="member.profile_updated").latest("id")
    assert entry.makerspace_id == space.pk
    assert entry.meta["visibility_changed"] is True
    assert entry.meta["is_visible"] is True
    # The log is append-only, so the bio must NOT be copied into it.
    assert "a private sentence" not in str(entry.meta)


def test_the_github_refresh_has_a_scheduled_task():
    """A command nobody runs leaves every count permanently None."""
    from django.conf import settings

    tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.makerspaces.tasks.refresh_github_contributions_task" in tasks


def test_the_github_task_is_inert_without_a_token(settings, monkeypatch):
    import urllib.request

    from apps.makerspaces.tasks import refresh_github_contributions_task

    settings.GITHUB_API_TOKEN = ""
    space = make_space("github-task")
    membership = member_of(space, "author")
    profile_services.save_profile(membership, {"github_username": "octocat"})

    def explode(*args, **kwargs):
        raise AssertionError("an unconfigured deployment must make no outbound call")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    assert refresh_github_contributions_task() == {"configured": False}


# --- fixes from the SECOND Codex Stage-4 pass --------------------------------------
#
# Round 1 came back clean on everything below. A review pass that finds nothing is not
# evidence there is nothing; it is one sample. Each of these is a defect the second
# pass found in code the first had already read.


@override_settings(
    DEBUG=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)
def test_a_walk_in_cannot_be_turned_into_an_account_by_forgot_password():
    """The unusable password is not the boundary -- `set_password` walks straight past it.

    Staff type an email address at the counter to reach someone about a loan. Whoever
    holds that mailbox could then request a reset and sign in, converting a person
    record into a real account and bypassing disabled self-registration entirely.
    """
    space = make_space("walkin-reset")
    front_desk = staffer(space)
    membership = create_walk_in_member(
        front_desk, space, display_name="Walk In", email="walkin@example.test"
    )

    response = APIClient().post(
        "/api/v1/auth/forgot-password", {"email": "walkin@example.test"}, format="json"
    )
    # The generic acknowledgement is unchanged -- refusing visibly would disclose which
    # addresses belong to walk-ins.
    assert response.status_code == 200
    claim = claim_pending_envelopes(owner="walk-in-regression")[0]
    assert prepare_delivery(claim) == PasswordResetEnvelopeStatus.DISCARDED
    membership.user.refresh_from_db()
    assert membership.user.has_usable_password() is False


def test_a_reset_token_is_refused_at_confirm_time_for_a_walk_in():
    """Checked on both paths: a link minted before the record was marked must still fail."""
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    space = make_space("walkin-reset-confirm")
    front_desk = staffer(space)
    membership = create_walk_in_member(
        front_desk, space, display_name="Walk In", email="confirm@example.test"
    )
    user = membership.user
    token = default_token_generator.make_token(user)

    response = APIClient().post(
        "/api/v1/auth/reset-password",
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": token,
            "password": "A brand new password 12!",
        },
        format="json",
    )
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.has_usable_password() is False


@override_settings(
    DEBUG=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
)
def test_an_ordinary_account_can_still_reset_its_password(monkeypatch):
    """The guard must be narrow -- a marker that catches everyone breaks account recovery."""
    space = make_space("ordinary-reset")
    user = staffer(space)
    assert user.is_walk_in is False

    response = APIClient().post(
        "/api/v1/auth/forgot-password", {"email": user.email}, format="json"
    )
    assert response.status_code == 200

    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    claim = claim_pending_envelopes(owner="ordinary-reset-regression")[0]
    attempt = prepare_delivery(claim)
    assert attempt is not None
    assert attempt.recipient == user.email


def event_for(space, **kwargs):
    from datetime import timedelta

    from django.utils import timezone

    from apps.events.models import Event

    now = timezone.now()
    return Event.objects.create(
        makerspace=space, title="Night", starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=2), is_public=True,
        status=Event.Status.PUBLISHED, **kwargs,
    )


def test_a_walk_in_without_an_email_can_still_be_registered_for_an_event():
    """`EventRegistration.email` is non-blank, so the members this program made
    registrable were exactly the ones that could not be registered."""
    from apps.events.models import EventRegistration

    space = make_space("event-walkin-email")
    manager_user = staffer(space, slug="space_manager", username="events-manager")
    front_desk = staffer(space, slug="space_manager", username="front-desk")
    membership = create_walk_in_member(front_desk, space, display_name="No Email")
    assert membership.user.email == ""
    event = event_for(space)

    # A walk-in created with a name alone has neither contact field, and the
    # registration model requires both -- so this exercises the email fallback added
    # here alongside the phone fallback that shipped with the staff endpoint.
    response = authed(manager_user).post(
        f"/api/v1/admin/events/{event.pk}/registrations/",
        {
            "member_id": membership.user_id,
            "email": "desk@example.test",
            "phone": "+15550100999",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    registration = EventRegistration.objects.get()
    assert registration.email == "desk@example.test"
    assert registration.phone == "+15550100999"


def test_the_account_email_still_wins_over_the_supplied_one():
    """The fallback must not become an override -- staff must not be able to redirect a
    member's event mail to an address of their choosing."""
    from apps.events.models import EventRegistration

    space = make_space("event-email-precedence")
    manager_user = staffer(space, slug="space_manager", username="events-manager")
    membership = member_of(space, "hasemail")
    event = event_for(space)

    response = authed(manager_user).post(
        f"/api/v1/admin/events/{event.pk}/registrations/",
        {"member_id": membership.user_id, "email": "attacker@example.test"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert EventRegistration.objects.get().email == membership.user.email.lower()


def test_purging_a_module_releases_the_storage_its_images_held(monkeypatch):
    """Deleting the rows without freeing the quota inflates the counter forever -- it
    keeps blocking uploads for storage nothing holds until an operator runs the
    reconciler by hand.

    Lives in `module_purge`, POST-COMMIT, and generic over every plan's keys: it was
    first written inside `membership_delete`, which runs in the purge transaction while
    the makerspace row is locked, so a slow or unavailable bucket would have held the
    lock across one HEAD per image and a `StorageUnavailable` would have rolled back the
    whole purge.
    """
    from apps.inventory import public_image_storage
    from apps.makerspaces import limits, module_purge

    space = make_space("purge-storage")
    key = build_object_key("member", space.pk, ".png")

    # Storage accounting is a no-op on self-host, so managed mode has to be forced.
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    monkeypatch.setattr(public_image_storage, "object_size", lambda object_key: 4096)
    monkeypatch.setattr(public_image_storage, "delete_object", lambda object_key: True)
    Makerspace.objects.filter(pk=space.pk).update(storage_bytes_used=10_000)

    module_purge._delete_public_images_and_free_storage(space, [key])

    space.refresh_from_db()
    assert space.storage_bytes_used == 10_000 - 4096


def test_storage_is_not_freed_when_the_object_delete_failed(monkeypatch):
    """`delete_object` swallows its own errors, so a failed delete is invisible.

    Freeing anyway decrements the counter while the object survives -- permanently
    undercounting, in the direction that hands a makerspace free storage.
    """
    from apps.inventory import public_image_storage
    from apps.makerspaces import limits, module_purge

    space = make_space("purge-storage-delete-failed")
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    monkeypatch.setattr(public_image_storage, "object_size", lambda object_key: 4096)
    monkeypatch.setattr(public_image_storage, "delete_object", lambda object_key: False)
    Makerspace.objects.filter(pk=space.pk).update(storage_bytes_used=10_000)

    module_purge._delete_public_images_and_free_storage(
        space, [build_object_key("member", space.pk, ".png")]
    )

    space.refresh_from_db()
    assert space.storage_bytes_used == 10_000


def test_freeing_storage_skips_an_object_that_is_already_gone(monkeypatch):
    """`object_size` returns None for a missing object; charging None back would
    corrupt the counter in the other direction."""
    from apps.inventory import public_image_storage
    from apps.makerspaces import limits, module_purge

    space = make_space("purge-storage-missing")
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    monkeypatch.setattr(public_image_storage, "object_size", lambda object_key: None)
    monkeypatch.setattr(public_image_storage, "delete_object", lambda object_key: True)
    Makerspace.objects.filter(pk=space.pk).update(storage_bytes_used=10_000)

    module_purge._delete_public_images_and_free_storage(
        space, [build_object_key("member", space.pk, ".png")]
    )

    space.refresh_from_db()
    assert space.storage_bytes_used == 10_000


def test_storage_accounting_never_breaks_a_purge(monkeypatch):
    """It runs after the rows are already gone, so raising would report a failure for
    work that succeeded -- and there is nothing left to roll back."""
    from apps.inventory import public_image_storage
    from apps.makerspaces import limits, module_purge

    space = make_space("purge-storage-unavailable")
    monkeypatch.setattr(limits, "is_self_host", lambda: False)

    def unavailable(object_key):
        from apps.evidence.storage import StorageUnavailable

        raise StorageUnavailable()

    monkeypatch.setattr(public_image_storage, "object_size", unavailable)
    monkeypatch.setattr(public_image_storage, "delete_object", lambda object_key: True)

    module_purge._delete_public_images_and_free_storage(
        space, [build_object_key("member", space.pk, ".png")]
    )


def test_a_github_count_is_never_written_under_a_changed_handle(monkeypatch):
    """A total under the wrong name is a false claim about a person, not stale data."""
    from apps.makerspaces import github_contributions

    space = make_space("github-handle-race")
    membership = member_of(space, "author")
    profile_services.save_profile(membership, {"github_username": "original"})
    profile = profile_services.profile_for(membership)

    def fetch_and_meanwhile_rename(login):
        assert login == "original"
        # The member edits their handle while the HTTP call is in flight.
        MemberProfile.objects.filter(pk=profile.pk).update(
            github_username="renamed", github_contributions=None
        )
        return 4321

    monkeypatch.setattr(github_contributions, "fetch_total", fetch_and_meanwhile_rename)
    assert github_contributions.refresh(profile) is False

    profile.refresh_from_db()
    assert profile.github_username == "renamed"
    assert profile.github_contributions is None, (
        "the old account's total must not land under the new handle"
    )


def test_a_github_count_is_stored_when_the_handle_is_unchanged(monkeypatch):
    """The filter must be narrow enough to still do its job."""
    from apps.makerspaces import github_contributions

    space = make_space("github-handle-stable")
    membership = member_of(space, "author")
    profile_services.save_profile(membership, {"github_username": "steady"})
    profile = profile_services.profile_for(membership)

    monkeypatch.setattr(github_contributions, "fetch_total", lambda login: 99)
    assert github_contributions.refresh(profile) is True

    profile.refresh_from_db()
    assert profile.github_contributions == 99
    assert profile.github_synced_at is not None


def set_presign_rate(monkeypatch, rate):
    """Override the cap for one test.

    Overriding `settings.REST_FRAMEWORK` does NOT work here: DRF binds
    `SimpleRateThrottle.THROTTLE_RATES` to the settings dict at import time, so a
    reloaded `api_settings` builds a new dict the class never sees. Patch the class.
    """
    from apps.makerspaces.throttles import MemberImagePresignThrottle

    monkeypatch.setattr(
        MemberImagePresignThrottle,
        "THROTTLE_RATES",
        {**MemberImagePresignThrottle.THROTTLE_RATES, "member_image_presign": rate},
    )


def stub_presign(monkeypatch):
    from apps.inventory import public_image_storage

    monkeypatch.setattr(
        public_image_storage, "presigned_upload",
        lambda object_key, content_type: {"url": "http://example.test", "fields": {}},
    )


def test_the_member_image_presign_is_capped_per_member(monkeypatch):
    """A presign hands out write access before any row claims the key, and nothing
    forces the caller back to attach. An unattached upload is invisible to the quota,
    to `recompute_storage` and to every purge path at once -- all three walk rows."""
    set_presign_rate(monkeypatch, "2/hour")
    stub_presign(monkeypatch)
    space = make_space("presign-cap")
    membership = member_of(space, "uploader")
    client = authed(membership.user)
    payload = {"filename": "a.png", "content_type": "image/png"}
    url = f"/api/v1/member/makerspaces/{space.pk}/profile/image"

    assert client.post(url, payload, format="json").status_code == 201
    assert client.post(url, payload, format="json").status_code == 201
    assert client.post(url, payload, format="json").status_code == 429


def test_the_presign_cap_does_not_block_clearing_an_image(monkeypatch):
    """Sharing one budget across the view's methods would let a member who spent their
    uploads lose the ability to CLEAR one -- the single action that frees storage."""
    from apps.inventory import public_image_storage

    set_presign_rate(monkeypatch, "1/hour")
    stub_presign(monkeypatch)
    space = make_space("presign-cap-clear")
    membership = member_of(space, "uploader")
    profile = profile_services.profile_for(membership)
    MemberProfile.objects.filter(pk=profile.pk).update(
        avatar_key=build_object_key("member", space.pk, ".png")
    )
    # Clearing frees the quota and deletes the object, so both storage calls are stubbed
    # -- MinIO is on a remapped host port here and the real ones raise StorageUnavailable.
    monkeypatch.setattr(public_image_storage, "delete_object", lambda object_key: None)
    monkeypatch.setattr(public_image_storage, "object_size", lambda object_key: 1024)
    client = authed(membership.user)
    url = f"/api/v1/member/makerspaces/{space.pk}/profile/image"

    assert client.post(
        url, {"filename": "a.png", "content_type": "image/png"}, format="json"
    ).status_code == 201
    assert client.post(
        url, {"filename": "b.png", "content_type": "image/png"}, format="json"
    ).status_code == 429
    assert client.delete(url).status_code == 200


def test_one_members_uploads_do_not_spend_anothers_budget(monkeypatch):
    """Keyed on the account, not the address: members share networks."""
    set_presign_rate(monkeypatch, "1/hour")
    stub_presign(monkeypatch)
    space = make_space("presign-cap-scope")
    mine = member_of(space, "mine")
    theirs = member_of(space, "theirs")
    payload = {"filename": "a.png", "content_type": "image/png"}
    url = f"/api/v1/member/makerspaces/{space.pk}/profile/image"

    assert authed(mine.user).post(url, payload, format="json").status_code == 201
    assert authed(mine.user).post(url, payload, format="json").status_code == 429
    assert authed(theirs.user).post(url, payload, format="json").status_code == 201


def test_social_sign_in_cannot_claim_a_walk_in_record():
    """The adjacent path to the forgot-password hole: another way to attach a login.

    Auto-link is already refused because a walk-in has no verified address, but that is
    an accident of walk-ins having no way to verify one rather than a rule about them.
    Asserted here so the boundary is the property, not the coincidence.
    """
    from apps.accounts.models_social import SocialSurface
    from apps.accounts.services_social_identity import (
        SocialResolutionError,
        resolve_social_identity,
    )

    space = make_space("walkin-social")
    front_desk = staffer(space)
    membership = create_walk_in_member(
        front_desk, space, display_name="Walk In", email="social@example.test"
    )
    # Force the one state that would otherwise permit an auto-link.
    User.objects.filter(pk=membership.user_id).update(
        email_verified_at=timezone.now()
    )

    with pytest.raises(SocialResolutionError) as raised:
        resolve_social_identity(
            provider="google",
            claims={
                "sub": "google-subject-1",
                "email": "social@example.test",
                "email_verified": True,
            },
            surface=SocialSurface.MEMBER,
            allow_auto_link=True,
        )
    assert raised.value.code == "account_link_required"
    membership.user.refresh_from_db()
    assert membership.user.has_usable_password() is False


# --- fixes from the THIRD Codex Stage-4 pass ---------------------------------------
#
# Round 2's fixes were themselves incomplete. Three more, two of them P1, and one of
# them showing a round-1 fix had never worked at all.


def test_staff_cannot_reset_a_walk_in_into_an_account():
    """The easier twin of the forgot-password hole, and it needs no mailbox at all.

    `reset_user_password` HANDS BACK a usable temporary password, so without this any
    space manager could convert a person record into a login in one click.
    """
    from rest_framework.exceptions import PermissionDenied

    from apps.admin_api.services_user_access import reset_user_password

    space = make_space("walkin-staff-reset")
    manager_user = staffer(space, slug="space_manager", username="reset-manager")
    front_desk = staffer(space, slug="space_manager", username="reset-desk")
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    with pytest.raises(PermissionDenied):
        reset_user_password(manager_user, membership.user_id)
    membership.user.refresh_from_db()
    assert membership.user.has_usable_password() is False


def test_an_ordinary_member_can_still_have_their_password_reset():
    """The refusal must be narrow, or it breaks the staff recovery path it sits on."""
    from apps.admin_api.services_user_access import reset_user_password

    space = make_space("ordinary-staff-reset")
    manager_user = staffer(space, slug="space_manager", username="reset-manager")
    membership = member_of(space, "ordinary")

    result = reset_user_password(manager_user, membership.user_id)
    assert result.temporary_password
    membership.user.refresh_from_db()
    assert membership.user.has_usable_password() is True


def test_the_walk_in_backfill_revokes_a_password_acquired_through_the_hole():
    """Marking the row is not enough on an upgrading database.

    A walk-in that already went through forgot-password before the flag existed holds a
    WORKING password, and the login path deliberately does not consult `is_walk_in` --
    the flag is enforced where a credential can be created, not where one is used. So a
    marker alone would leave exactly the accounts this migration exists for able to sign
    in.
    """
    from importlib import import_module

    from django.apps import apps as global_apps

    # Imported by string: the module name starts with a digit, so it cannot be spelled
    # as an `import` statement.
    backfill = import_module("apps.accounts.migrations.0015_backfill_is_walk_in")

    space = make_space("walkin-backfill")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")
    # Simulate the pre-0014 state: the record went through forgot-password and now has a
    # usable password, and the audit entry naming it is already on disk.
    membership.user.set_password(PASSWORD)
    membership.user.is_walk_in = False
    membership.user.save(update_fields=["password", "is_walk_in"])
    assert membership.user.has_usable_password() is True

    backfill.mark_walk_ins(global_apps, None)

    membership.user.refresh_from_db()
    assert membership.user.is_walk_in is True
    assert membership.user.has_usable_password() is False, (
        "a credential acquired through the hole must not survive the migration"
    )


# --- fixes from the FOURTH Codex Stage-4 pass --------------------------------------


def test_the_backfill_revokes_durable_identities_not_just_the_password():
    """A password reset does not reach what the session it opened was used to link.

    A walk-in who went through the old hole had a working login, and could have used it
    to attach a Google account, verify a phone number, or register a device -- each of
    which has a login path that never reaches the `is_walk_in` guard. Revoking only the
    password leaves all three minting fresh tokens after the upgrade.
    """
    from importlib import import_module

    from django.apps import apps as global_apps

    from apps.accounts.models_devices import DeviceGrant
    from apps.accounts.models_social import SocialIdentity

    backfill = import_module("apps.accounts.migrations.0015_backfill_is_walk_in")

    space = make_space("walkin-durable")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")
    user = membership.user
    # The pre-0014 state: a working password, and everything that session could link.
    user.set_password(PASSWORD)
    user.is_walk_in = False
    user.phone_e164 = "+15550100777"
    user.phone_verified_at = timezone.now()
    user.save(
        update_fields=["password", "is_walk_in", "phone_e164", "phone_verified_at"]
    )
    SocialIdentity.objects.create(
        user=user, provider="google", provider_sub="walkin-subject"
    )
    grant = DeviceGrant.objects.create(
        user=user, platform="ios", app_id="test.app", signing_identity="sig",
        environment="production", attestation_subject_fingerprint="f" * 64,
        attested_at=timezone.now(), last_used_at=timezone.now(),
    )

    backfill.mark_walk_ins(global_apps, None)

    user.refresh_from_db()
    grant.refresh_from_db()
    assert user.is_walk_in is True
    assert user.has_usable_password() is False
    assert not SocialIdentity.objects.filter(user=user).exists(), (
        "a linked provider signs them in before any is_walk_in guard runs"
    )
    assert user.phone_e164 == ""
    assert user.phone_verified_at is None
    assert grant.status == "revoked"
    assert grant.revoked_at is not None


# --- fixes from the FIFTH Codex Stage-4 pass ---------------------------------------


def test_a_walk_in_cannot_link_a_provider_with_a_live_access_token():
    """The migration revokes refresh tokens; an ACCESS token outlives it by ~15 minutes.

    `_explicit_link` is reached before the auto-link guard, so within that window a
    walk-in could attach a NEW provider identity and regain permanent access -- undoing
    the migration that had just deleted their old ones. The guard therefore lives inside
    `_explicit_link`, where every explicit link is created, not at the caller.
    """
    from apps.accounts.models_social import SocialIdentity
    from apps.accounts.services_social_identity import (
        SocialResolutionError,
        resolve_social_identity,
    )

    space = make_space("walkin-explicit-link")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    with pytest.raises(SocialResolutionError) as raised:
        resolve_social_identity(
            provider="google",
            claims={"sub": "sub-explicit", "email": "x@example.test"},
            surface="member",
            explicit_user=membership.user,
        )
    assert raised.value.code == "walk_in_record"
    assert raised.value.status_code == 403
    assert not SocialIdentity.objects.filter(user=membership.user).exists()


def test_an_ordinary_member_can_still_link_a_provider():
    """The refusal must not reach real accounts -- linking is a normal member action."""
    from apps.accounts.models_social import SocialIdentity
    from apps.accounts.services_social_identity import resolve_social_identity

    space = make_space("ordinary-explicit-link")
    membership = member_of(space, "linker")

    user, outcome = resolve_social_identity(
        provider="google",
        claims={"sub": "sub-ordinary", "email": membership.user.email},
        surface="member",
        explicit_user=membership.user,
    )
    assert outcome == "linked"
    assert user.pk == membership.user_id
    assert SocialIdentity.objects.filter(
        user=membership.user, provider="google"
    ).exists()


# --- fixes from the SIXTH Codex Stage-4 pass ---------------------------------------


def test_a_walk_in_cannot_link_a_verified_phone(settings, monkeypatch):
    """The fifth credential-writer on this seam, and the fifth round to find one.

    A verified `phone_e164` IS a login identity, resolved by number -- so a walk-in
    holding a live access token could rebuild OTP login after migration 0015 revoked
    everything else. The guard is inside `confirm_link`'s transaction, on a row re-read
    under `select_for_update`: the caller's `user` came off a JWT and may be stale.
    """
    from apps.accounts import services_phone

    space = make_space("walkin-phone-link")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    # `start_link` is refused too -- it writes a challenge row and spends an SMS.
    monkeypatch.setattr(services_phone, "sms_configured", lambda: True)
    with pytest.raises(Exception):
        services_phone.start_link(membership.user, "+15550100888")

    # And the confirm side, which is the chokepoint that actually writes the identity.
    with pytest.raises(Exception):
        services_phone.confirm_link(membership.user, "+15550100888", "000000")

    membership.user.refresh_from_db()
    assert membership.user.phone_e164 == ""
    assert membership.user.phone_verified_at is None


# --- fixes from the SEVENTH Codex pass, and the enumeration guards -----------------


def test_a_walk_in_is_not_enrollable_by_a_stranger_who_knows_the_email():
    """Sign-up reuses an existing row by email. A walk-in must not be enrollable.

    It never wrote a password onto an existing row, so this was never a login -- but it
    let an unauthenticated stranger trigger a verification mail to the mailbox staff
    typed at the counter and stamp `email_verified_at` on a record they do not own.
    Silence, not an error: the endpoint's contract is that it never discloses whether an
    account exists.
    """
    from apps.accounts.models import EmailVerificationChallenge
    from apps.accounts.services_registration import register_member

    space = make_space("walkin-signup")
    front_desk = staffer(space)
    membership = create_walk_in_member(
        front_desk, space, display_name="Walk In", email="enroll@example.test"
    )

    assert register_member(
        display_name="Impostor", email="enroll@example.test",
        phone="+15550100123", password="A perfectly fine password 9!",
    ) is None

    membership.user.refresh_from_db()
    assert membership.user.email_verified_at is None
    assert membership.user.has_usable_password() is False
    assert not EmailVerificationChallenge.objects.filter(user=membership.user).exists()


def test_a_walk_in_cannot_reach_the_change_password_endpoint():
    """Unreachable today because `check_password` fails on an unusable password. Pinned
    so it stays refused for a stated reason rather than by side effect."""
    space = make_space("walkin-change-password")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    response = authed(membership.user).post(
        "/api/v1/auth/change-password",
        {"current_password": PASSWORD, "new_password": "Another good password 42!"},
        format="json",
    )
    assert response.status_code == 400
    membership.user.refresh_from_db()
    assert membership.user.has_usable_password() is False


def test_the_seed_command_refuses_to_overwrite_a_walk_in():
    """A username collision must be loud, not a silent password write on a person."""
    from django.core.management.base import CommandError

    from apps.inventory.management.commands.seed_demo import Command

    space = make_space("walkin-seed")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    with pytest.raises(CommandError):
        Command()._user(
            membership.user.username, "x@example.test", "pw", User.Role.REQUESTER
        )


def test_rate_limits_use_a_shared_cache_when_one_is_configured():
    """A per-process cache silently multiplies every throttle by the worker count.

    Asserted against `cache_config` with real inputs rather than against the live
    `settings.CACHES`: the test session deliberately runs on LocMem (see
    `tests/conftest.py`), so the live value says nothing about what a deployment gets.
    The brokerless cloud profile is the case that matters -- it supplies no Redis URL
    and still runs three gunicorn workers with `--max-requests` recycling.
    """
    from config.settings import cache_config

    assert cache_config("redis://cache:6379/1") == {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://cache:6379/1",
    }
    # No Redis must NOT mean per-process; that was the round-9 defect.
    without_redis = cache_config("")
    assert without_redis["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"
    assert "locmem" not in without_redis["BACKEND"]
    # And it must raise the entry ceiling -- the round-12 defect. Django's DatabaseCache
    # defaults to 300 rows and culls a third once exceeded, and a throttle key is one row
    # per (scope, identity). At the default, roughly twenty callers across this
    # deployment's dozen-plus scoped throttles would start evicting UNEXPIRED login, OTP
    # and password-reset histories, letting someone rotating identities reset their own
    # cap. Choosing DatabaseCache without raising this limit fixes the multi-worker
    # bypass and leaves an eviction bypass in its place.
    assert without_redis["OPTIONS"]["MAX_ENTRIES"] >= 50_000


@pytest.mark.django_db(transaction=True)
def test_the_scheduler_does_not_hold_a_lock_across_network_calls(monkeypatch):
    """The GitHub refresh makes one HTTP call per profile with a 10s timeout, so it must
    not hold the PeriodicTaskRun row lock while those network calls execute.

    Claim-then-work is at-most-once, which this file already argues is the right trade
    for the return reminder.
    """
    from django.core.management import call_command
    from django.db import transaction

    from apps.makerspaces import tasks

    observed_atomic_states = []

    def refresh_stub():
        observed_atomic_states.append(transaction.get_connection().in_atomic_block)

    monkeypatch.setattr(tasks, "refresh_github_contributions_task", refresh_stub)

    # This used to scan source text, which could pass with the task still inside atomic()
    # and broke on harmless refactors. transaction=True removes pytest-django's outer
    # atomic wrapper while retaining its database cleanup, so runtime state is observable.
    call_command("run_scheduled_tasks", task="refresh-github-contributions")

    assert observed_atomic_states == [False]


def test_the_backfill_finds_a_walk_in_whose_makerspace_was_purged():
    """A6 was accepted on a false premise and is now retired.

    The audit trail is makerspace-scoped, so a tenant purge deletes it while the global
    `User` survives -- which is exactly the row that stays convertible. Every walk-in
    username is generated as `walkin_<name>_<random>`, on the global row, so it survives
    the purge. Self-registration uses `member_<uuid>`, so the namespaces cannot collide.

    The post-purge state is built directly rather than by purging: the audit log is
    append-only and its triggers refuse the DELETE outside a purge transaction, which is
    itself the reason the audit trail cannot be relied on here.
    """
    from importlib import import_module

    from django.apps import apps as global_apps

    backfill = import_module("apps.accounts.migrations.0015_backfill_is_walk_in")

    # Exactly what a purge leaves behind: the global row, no membership, no audit -- and
    # a password it acquired through the hole before the flag existed.
    orphan = User.objects.create_user(
        username="walkin_purged_person_ab12cd",
        email="purged@example.test",
        password=PASSWORD,
        access_status=User.AccessStatus.ACTIVE,
    )
    assert orphan.is_walk_in is False

    backfill.mark_walk_ins(global_apps, None)

    orphan.refresh_from_db()
    assert orphan.is_walk_in is True, "the username prefix is what survives a tenant purge"
    assert orphan.has_usable_password() is False


def test_a_self_registered_account_is_never_marked_by_the_prefix_match():
    """The prefix must not be a net wide enough to catch a real member.

    Self-registration generates `member_<uuid>`, so a genuine account keeps its password
    and its unmarked status through the backfill.
    """
    from importlib import import_module

    from django.apps import apps as global_apps

    backfill = import_module("apps.accounts.migrations.0015_backfill_is_walk_in")

    genuine = User.objects.create_user(
        username="member_9f2c41aa",
        email="genuine@example.test",
        password=PASSWORD,
        access_status=User.AccessStatus.ACTIVE,
    )

    backfill.mark_walk_ins(global_apps, None)

    genuine.refresh_from_db()
    assert genuine.is_walk_in is False
    assert genuine.has_usable_password() is True, (
        "a real member must keep the password the backfill had no business touching"
    )


def test_a_refused_walk_in_phone_link_is_audited():
    """`_confirm` has already consumed the challenge by the time the guard runs, so a
    state change happened. Every state-changing path in this repo emits an audit row."""
    from apps.accounts import services_phone
    from apps.audit.models import AuditLog

    space = make_space("walkin-phone-audit")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    with pytest.raises(Exception):
        services_phone.confirm_link(membership.user, "+15550100999", "000000")

    # Either the refusal or the generic confirm failure must be on the record -- what
    # must never happen is a consumed challenge with no trace at all.
    assert AuditLog.objects.filter(
        action__in=[
            "member.phone_link_refused_walk_in",
            "member.phone_link_failed",
        ]
    ).exists()
