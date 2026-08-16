from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient

from apps.accounts import services_claim
from apps.accounts.models import MemberClaimCode, User
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("change", ["suspended", "deactivated", "temporary_password"])
def test_issuer_change_after_request_authorization_but_before_lock_is_refused(
    monkeypatch, change
):
    makerspace = Makerspace.objects.create(name=f"Race {change}", slug=f"race-{change}")
    issuer = make_handout_member(f"race-issuer-{change}", makerspace)
    target = User(
        username=f"race-target-{change}",
        is_walk_in=True,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    target.set_unusable_password()
    target.save()
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=target, role=MakerspaceMembership.Role.CUSTOM
    )
    authorized = Event()
    continue_to_lock = Event()
    real_lock = services_claim.lock_and_validate_staff_authority

    def pause_after_api_authorization(**kwargs):
        authorized.set()
        assert continue_to_lock.wait(timeout=5)
        return real_lock(**kwargs)

    monkeypatch.setattr(
        services_claim,
        "lock_and_validate_staff_authority",
        pause_after_api_authorization,
    )

    def request_issue():
        close_old_connections()
        client = APIClient()
        # This stale authenticated instance is deliberate: the permission check passes,
        # then the service must reload the actor under its lock after the competing write.
        client.force_authenticate(issuer)
        try:
            return client.post(
                f"/api/v1/admin/makerspaces/{makerspace.pk}/member-claim-codes",
                {"membership_id": membership.pk},
                format="json",
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(request_issue)
        assert authorized.wait(timeout=5)
        if change == "suspended":
            User.objects.filter(pk=issuer.pk).update(
                access_status=User.AccessStatus.SUSPENDED
            )
        elif change == "deactivated":
            User.objects.filter(pk=issuer.pk).update(is_active=False)
        else:
            User.objects.filter(pk=issuer.pk).update(must_change_password=True)
        continue_to_lock.set()
        response = future.result(timeout=5)

    assert response.status_code == 403
    assert not MemberClaimCode.objects.filter(membership=membership).exists()

