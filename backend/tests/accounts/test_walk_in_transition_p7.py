import pytest
from django.contrib.auth import authenticate
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from apps.accounts.tokens import SpaceWorksRefreshToken

from apps.accounts import services_registration
from apps.accounts.models import EmailVerificationChallenge, User
from apps.accounts.models_devices import DeviceGrant
from apps.accounts.services_device_tokens import issue_device_token_pair
from apps.accounts.transition_services import (
    register_walk_in_revocation_hook,
    transition_walk_in_to_account,
    unregister_walk_in_revocation_hook,
)
from apps.audit.models import AuditLog
from tests.device_helpers import make_native_app_registration

pytestmark = pytest.mark.django_db(transaction=True)
PASSWORD = "Safe transition password 947!"
ACK = "If the details are valid, a verification email has been sent."


def make_walk_in(username="walk-in-transition", email="walk-in@example.test"):
    user = User(
        username=username,
        email=email,
        is_walk_in=True,
        is_active=True,
    )
    user.set_unusable_password()
    user.save()
    return user


def assert_transition_write_refused(write):
    user = make_walk_in(username=f"guarded-{User.objects.count()}", email="")
    with pytest.raises(DatabaseError), transaction.atomic():
        write(user)
    assert User.objects.get(pk=user.pk).is_walk_in is True


def test_trigger_refuses_every_direct_update_shape():
    def instance_save(user):
        user.is_walk_in = False
        user.save(update_fields=["is_walk_in"])

    def queryset_update(user):
        User.objects.filter(pk=user.pk).update(is_walk_in=False)

    def bulk_update(user):
        user.is_walk_in = False
        User.objects.bulk_update([user], ["is_walk_in"])

    def raw_sql(user):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE accounts_user SET is_walk_in = FALSE WHERE id = %s",
                [user.pk],
            )

    for write in (instance_save, queryset_update, bulk_update, raw_sql):
        assert_transition_write_refused(write)


def test_transition_revokes_every_token_and_fires_hooks_in_one_transaction():
    actor = User.objects.create_superuser(
        username="transition-actor", email="actor@example.test", password=PASSWORD
    )
    user = make_walk_in()
    SpaceWorksRefreshToken.for_user(user)
    grant = DeviceGrant.objects.create(
        registration=make_native_app_registration(app_id="test.app"),
        user=user,
        platform="apple",
        app_id="test.app",
        signing_identity="test-signing",
        environment="development",
        attestation_subject_fingerprint="f" * 64,
        attested_at=timezone.now(),
        last_used_at=timezone.now(),
    )
    _, _, family = issue_device_token_pair(user, grant)
    hook_observations = []
    credential_observations = []

    def revoke_claim_state(locked_user, transitioned_at):
        hook_observations.append(
            (
                connection.in_atomic_block,
                User.objects.get(pk=locked_user.pk).is_walk_in,
                transitioned_at is not None,
            )
        )

    def write_password(locked_user):
        family.refresh_from_db()
        credential_observations.append(
            (
                connection.in_atomic_block,
                bool(hook_observations),
                family.revoked_at is not None,
                BlacklistedToken.objects.filter(token__user=locked_user).count()
                == OutstandingToken.objects.filter(user=locked_user).count(),
            )
        )
        locked_user.set_password(PASSWORD)
        locked_user.save(update_fields=["password"])

    register_walk_in_revocation_hook("test-claim-state", revoke_claim_state)
    try:
        transitioned = transition_walk_in_to_account(
            user, actor=actor, credential_writer=write_password
        )
    finally:
        unregister_walk_in_revocation_hook("test-claim-state")

    transitioned.refresh_from_db()
    grant.refresh_from_db()
    family.refresh_from_db()
    assert hook_observations == [(True, False, True)]
    assert credential_observations == [(True, True, True, True)]
    assert transitioned.is_walk_in is False
    assert transitioned.check_password(PASSWORD)
    assert grant.status == DeviceGrant.Status.REVOKED
    assert family.revoked_at is not None
    assert AuditLog.objects.filter(
        actor=actor,
        action="member.walk_in_transitioned",
        target_id=str(user.pk),
    ).exists()


def test_transition_failure_rolls_back_marker_hook_and_token_revocation():
    user = make_walk_in("transition-rollback", "")
    SpaceWorksRefreshToken.for_user(user)
    grant = DeviceGrant.objects.create(
        registration=make_native_app_registration(app_id="rollback.app"),
        user=user,
        platform="apple",
        app_id="rollback.app",
        signing_identity="rollback-signing",
        environment="development",
        attestation_subject_fingerprint="r" * 64,
        attested_at=timezone.now(),
        last_used_at=timezone.now(),
    )
    _, _, family = issue_device_token_pair(user, grant)

    def revoke_claim_state(locked_user, _transitioned_at):
        locked_user.first_name = "hook-ran"
        locked_user.save(update_fields=["first_name"])

    def fail_credential_write(_locked_user):
        raise RuntimeError("credential write failed")

    register_walk_in_revocation_hook("test-rollback", revoke_claim_state)
    try:
        with pytest.raises(RuntimeError, match="credential write failed"):
            transition_walk_in_to_account(
                user, actor=None, credential_writer=fail_credential_write
            )
    finally:
        unregister_walk_in_revocation_hook("test-rollback")

    user.refresh_from_db()
    grant.refresh_from_db()
    family.refresh_from_db()
    assert user.is_walk_in is True
    assert user.first_name == ""
    assert grant.status == DeviceGrant.Status.ACTIVE
    assert family.revoked_at is None
    assert not BlacklistedToken.objects.filter(token__user=user).exists()


def test_transition_guc_does_not_leak_to_the_next_transaction():
    user = make_walk_in("guc-transition", "")
    transition_walk_in_to_account(user, actor=None)

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.allow_walk_in_transition', true)")
        assert cursor.fetchone()[0] != "on"

    assert_transition_write_refused(
        lambda later: User.objects.filter(pk=later.pk).update(is_walk_in=False)
    )


def test_walk_in_email_verification_issue_and_confirm_are_generic(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        services_registration,
        "send_email_verification_otp",
        lambda *_: dispatched.append(True) or True,
    )
    user = make_walk_in("walk-in-email-issue", "issue-walk-in@example.test")
    client = APIClient()
    client.force_authenticate(user)

    issued = client.post("/api/v1/auth/email-verification/resend", format="json")

    assert issued.status_code == 200
    assert issued.data == {"detail": ACK}
    assert not EmailVerificationChallenge.objects.filter(user=user).exists()
    assert dispatched == []

    confirmer = User.objects.create_user(
        username="walk-in-email-confirm",
        email="confirm-walk-in@example.test",
        password=PASSWORD,
    )
    challenge = EmailVerificationChallenge.objects.create(
        user=confirmer,
        email=confirmer.email,
        code_digest=services_registration._digest("123456"),
        expires_at=timezone.now() + services_registration.CHALLENGE_TTL,
    )
    User.objects.filter(pk=confirmer.pk).update(is_walk_in=True)
    client.force_authenticate(confirmer)

    confirmed = client.post(
        "/api/v1/auth/email-verification/confirm",
        {"code": "123456"},
        format="json",
    )

    assert confirmed.status_code == 400
    assert confirmed.data == {"detail": services_registration.GENERIC_CONFIRM_ERROR}
    challenge.refresh_from_db()
    confirmer.refresh_from_db()
    assert challenge.consumed_at is not None
    assert confirmer.email_verified_at is None
    assert AuditLog.objects.filter(
        actor=confirmer,
        action="member.email_verification_refused_walk_in",
        target_id=str(confirmer.pk),
    ).exists()


def test_admin_password_form_transitions_walk_in_before_setting_credential():
    admin = User.objects.create_superuser(
        username="walk-in-admin", email="admin@example.test", password=PASSWORD
    )
    user = make_walk_in("walk-in-admin-target", "admin-target@example.test")
    client = Client()
    client.force_login(admin)

    response = client.post(
        reverse("admin:auth_user_password_change", args=[user.pk]),
        {"password1": PASSWORD, "password2": PASSWORD},
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.is_walk_in is False
    assert user.has_usable_password() is True
    assert authenticate(username=user.username, password=PASSWORD) == user
    assert AuditLog.objects.filter(
        actor=admin,
        action="member.walk_in_transitioned",
        target_id=str(user.pk),
    ).exists()
