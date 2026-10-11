"""Imported admission policy replaces the new-tenant signal's placeholder."""

from decimal import Decimal

import pytest

from apps.makerspaces.models import MakerspaceMembershipSettings, MembershipPlan
from apps.tenant_migration.materialization import materialize_tenant
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case


pytestmark = pytest.mark.django_db(transaction=True)


def test_admission_policy_round_trips_once_with_remapped_plan_and_target_authority():
    with enabled_encryption():
        user = make_user("admission-roundtrip")
        source = make_space("admission-roundtrip")
        plan = MembershipPlan.objects.create(
            makerspace=source, name="Portable plan", interval="monthly",
            amount=Decimal("35.00"),
        )
        settings = MakerspaceMembershipSettings.objects.get(makerspace=source)
        settings.configured = True
        settings.join_mode = "open"
        settings.vouch_replaces_approval = True
        settings.voucher_pending_limit = 7
        settings.joining_fee = Decimal("12.00")
        settings.default_plan = plan
        settings.save()

        with portable_import_case(source, user) as case:
            case.decide_walk_in(user)
            result = materialize_tenant(
                case.root, case.job, case.carried,
                target_identity={"slug": "admission-roundtrip-target"},
            )

    imported = MakerspaceMembershipSettings.objects.get(
        makerspace_id=result.target_makerspace_id,
    )
    assert result.imported["makerspaces.MakerspaceMembershipSettings"] == 1
    assert imported.configured is True
    assert imported.join_mode == "approval"
    assert imported.vouch_replaces_approval is False
    assert imported.voucher_pending_limit == 7
    assert imported.joining_fee == Decimal("12.00")
    assert imported.default_plan_id != plan.pk
    assert imported.default_plan.makerspace_id == result.target_makerspace_id
    assert imported.default_plan.name == plan.name
    settings.refresh_from_db()
    assert settings.join_mode == "open"
    assert settings.default_plan_id == plan.pk
