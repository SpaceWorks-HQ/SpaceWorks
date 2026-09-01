import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceArchiveRequest

pytestmark = pytest.mark.django_db


def superadmin():
    return User.objects.create_user(
        username="archive-request-admin",
        email="archive-request-admin@example.test",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )


def request_for(slug, requester):
    makerspace = Makerspace.objects.create(name=slug, slug=slug)
    archive_request = MakerspaceArchiveRequest.objects.create(
        makerspace=makerspace,
        requested_by=requester,
        reason=f"Archive {slug}",
    )
    return makerspace, archive_request


def test_control_approve_action_confirms_impact_before_archiving():
    """Approving IS archiving, so it must show the same impact the direct route shows.

    The first version archived straight from the changelist, which meant a superadmin could
    approve without ever seeing the owned/routed pending charges that the direct archive
    action puts in front of them -- two ways to do one thing, one of them uninformed.
    """
    actor = superadmin()
    makerspace, archive_request = request_for("archive-admin-approve", actor)
    client = Client()
    client.force_login(actor)
    action = {
        "action": "approve_selected",
        ACTION_CHECKBOX_NAME: [str(archive_request.pk)],
        "index": "0",
    }

    confirmation = client.post(
        reverse("admin:makerspaces_makerspacearchiverequest_changelist"), action
    )

    assert confirmation.status_code == 200
    assert confirmation.template_name == (
        "admin/makerspaces/archive_request_approve_confirmation.html"
    )
    makerspace.refresh_from_db()
    assert makerspace.archived_at is None, "must not archive before confirmation"
    row = confirmation.context_data["requests"][0]
    assert {"owned_pending", "routed_pending", "total_pending"} <= set(row)

    response = client.post(
        reverse("admin:makerspaces_makerspacearchiverequest_changelist"),
        {**action, "confirm_archive_requests": "1"},
    )

    assert response.status_code == 302
    archive_request.refresh_from_db()
    makerspace.refresh_from_db()
    assert archive_request.status == MakerspaceArchiveRequest.Status.APPROVED
    assert makerspace.archived_at is not None


def test_control_decline_action_requires_and_records_note():
    actor = superadmin()
    makerspace, archive_request = request_for("archive-admin-decline", actor)
    client = Client()
    client.force_login(actor)
    url = reverse("admin:makerspaces_makerspacearchiverequest_changelist")
    selection = {
        "action": "decline_selected",
        ACTION_CHECKBOX_NAME: [str(archive_request.pk)],
        "index": "0",
    }

    confirmation = client.post(url, selection)
    assert confirmation.status_code == 200
    assert "Resolution note" in confirmation.content.decode()

    response = client.post(
        url,
        {
            **selection,
            "confirm_decline": "1",
            "resolution_note": "The closure is temporary.",
        },
    )

    assert response.status_code == 302
    archive_request.refresh_from_db()
    makerspace.refresh_from_db()
    assert archive_request.status == MakerspaceArchiveRequest.Status.DECLINED
    assert archive_request.resolution_note == "The closure is temporary."
    assert makerspace.archived_at is None
