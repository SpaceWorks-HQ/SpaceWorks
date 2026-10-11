"""Tenant creation provisions defaults; a portable import owns its carried policy."""
import pytest

from apps.accounts.models import User
from apps.makerspaces.membership_admission_settings import update_settings
from apps.makerspaces.models import Makerspace, MakerspaceMembershipSettings

pytestmark = pytest.mark.django_db


def test_ordinary_creation_and_settings_edits_share_one_policy_row():
    space = Makerspace.objects.create(
        name="Admission defaults", slug="admission-defaults", membership_policy="open",
        membership_dues_amount="12.00",
    )
    policy = MakerspaceMembershipSettings.objects.get(makerspace=space)
    assert not policy.configured and policy.join_mode == "open"
    assert str(policy.joining_fee) == "12.00"
    actor = User.objects.create_user(username="admission-defaults-root", is_superuser=True)
    updated = update_settings(actor, space, {"join_mode": "approval"})
    assert updated.pk == policy.pk and updated.configured
    assert MakerspaceMembershipSettings.objects.filter(makerspace=space).count() == 1


def test_importing_root_does_not_preempt_the_carried_admission_policy():
    space = Makerspace.objects.create(
        name="Import target", slug="admission-import-target",
        lifecycle_state=Makerspace.LifecycleState.IMPORTING,
    )
    assert not MakerspaceMembershipSettings.objects.filter(makerspace=space).exists()
    carried = MakerspaceMembershipSettings.objects.create(
        makerspace=space, configured=True, join_mode="closed", joining_fee="25.00",
    )
    space.lifecycle_state = Makerspace.LifecycleState.ACTIVE
    space.save(update_fields=["lifecycle_state"])
    assert MakerspaceMembershipSettings.objects.get(makerspace=space).pk == carried.pk
