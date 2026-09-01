from decimal import Decimal

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import lifecycle
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceArchiveRequest,
    MakerspaceMembership,
)
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def make_user(username, **overrides):
    defaults = {
        "email": f"{username}@example.com",
        "access_status": User.AccessStatus.ACTIVE,
    }
    defaults.update(overrides)
    return User.objects.create_user(username=username, **defaults)


def make_superadmin(username="archive-impact-superadmin"):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_membership_payment(
    makerspace,
    actor,
    suffix,
    *,
    status=Payment.Status.PENDING,
    via_makerspace=None,
):
    member = make_user(f"archive-impact-{suffix}")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=member,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return Payment.objects.create(
        makerspace=makerspace,
        via_makerspace=via_makerspace,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        subject_label="Membership dues",
        member=member,
        amount=Decimal("10.00"),
        currency="usd",
        status=status,
        created_by=actor,
    )


def test_archive_impact_counts_owned_pending_payment():
    actor = make_superadmin()
    makerspace = make_space("archive-impact-owned")
    make_membership_payment(makerspace, actor, "owned")

    assert lifecycle.archive_impact(makerspace) == {
        "owned_pending": 1,
        "routed_pending": 0,
        "total_pending": 1,
    }


def test_archive_impact_counts_routed_pending_without_double_counting_owned():
    actor = make_superadmin()
    makerspace = make_space("archive-impact-routed")
    host = make_space("archive-impact-host")
    make_membership_payment(
        host,
        actor,
        "routed",
        via_makerspace=makerspace,
    )
    make_membership_payment(
        makerspace,
        actor,
        "owned-and-routed",
        via_makerspace=makerspace,
    )

    assert lifecycle.archive_impact(makerspace) == {
        "owned_pending": 1,
        "routed_pending": 1,
        "total_pending": 2,
    }


def test_archive_impact_ignores_terminal_payments():
    actor = make_superadmin()
    makerspace = make_space("archive-impact-terminal")
    host = make_space("archive-impact-terminal-host")
    for index, status in enumerate(
        (
            Payment.Status.PAID_ONLINE,
            Payment.Status.PAID_OFFLINE,
            Payment.Status.WAIVED,
            Payment.Status.CANCELED,
        )
    ):
        make_membership_payment(
            makerspace,
            actor,
            f"terminal-{index}",
            status=status,
        )
        make_membership_payment(
            host,
            actor,
            f"terminal-routed-{index}",
            status=status,
            via_makerspace=makerspace,
        )

    assert lifecycle.archive_impact(makerspace) == {
        "owned_pending": 0,
        "routed_pending": 0,
        "total_pending": 0,
    }


def test_archive_succeeds_with_pending_payments_and_audits_impact():
    actor = make_superadmin()
    makerspace = make_space("archive-impact-audit")
    host = make_space("archive-impact-audit-host")
    make_membership_payment(makerspace, actor, "audit-owned")
    make_membership_payment(
        host,
        actor,
        "audit-routed",
        via_makerspace=makerspace,
    )

    archived = lifecycle.archive(makerspace, actor)

    assert archived.pk == makerspace.pk
    assert archived.archived_at is not None
    entry = AuditLog.objects.get(
        action="makerspace.archived",
        target_id=str(makerspace.pk),
    )
    assert entry.meta == {
        "owned_pending": 1,
        "routed_pending": 1,
        "total_pending": 2,
    }


def test_archive_admin_action_requires_confirmation_before_archiving():
    actor = make_superadmin()
    makerspace = make_space("archive-impact-admin")
    empty_makerspace = make_space("archive-impact-admin-empty")
    pending = MakerspaceArchiveRequest.objects.create(
        makerspace=makerspace,
        requested_by=actor,
        reason="The lease has ended and the workshop is closing.",
    )
    make_membership_payment(makerspace, actor, "admin-owned")
    client = Client()
    client.force_login(actor)
    url = reverse("admin:makerspaces_makerspace_changelist")
    action_data = {
        "action": "archive_makerspaces",
        ACTION_CHECKBOX_NAME: [str(makerspace.pk), str(empty_makerspace.pk)],
        "index": "0",
    }

    confirmation = client.post(url, action_data)

    makerspace.refresh_from_db()
    empty_makerspace.refresh_from_db()
    assert confirmation.status_code == 200
    assert confirmation.template_name == "admin/makerspaces/archive_confirmation.html"
    assert makerspace.archived_at is None
    assert empty_makerspace.archived_at is None
    impacts = {
        row["object"].slug: {
            "owned_pending": row["owned_pending"],
            "routed_pending": row["routed_pending"],
            "total_pending": row["total_pending"],
        }
        for row in confirmation.context_data["makerspaces"]
    }
    assert impacts == {
        "archive-impact-admin": {
            "owned_pending": 1,
            "routed_pending": 0,
            "total_pending": 1,
        },
        "archive-impact-admin-empty": {
            "owned_pending": 0,
            "routed_pending": 0,
            "total_pending": 0,
        },
    }
    content = confirmation.content.decode()
    assert "ADVISORY" in content
    assert "does NOT block" in content
    assert f'name="{ACTION_CHECKBOX_NAME}" value="{makerspace.pk}"' in content
    assert f'name="{ACTION_CHECKBOX_NAME}" value="{empty_makerspace.pk}"' in content
    assert "archive-impact-admin" in content
    assert "archive-impact-admin-empty" in content
    assert "pending archive request" in content.lower()
    assert "The lease has ended and the workshop is closing." in content

    confirmed = client.post(url, {**action_data, "confirm_archive": "1"})

    makerspace.refresh_from_db()
    empty_makerspace.refresh_from_db()
    assert confirmed.status_code == 302
    assert makerspace.archived_at is not None
    assert empty_makerspace.archived_at is not None
    pending.refresh_from_db()
    assert pending.status == MakerspaceArchiveRequest.Status.APPROVED
