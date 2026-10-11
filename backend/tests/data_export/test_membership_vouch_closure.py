"""Vouches travel only as history attached to retained applications."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.makerspaces.models import MembershipRequest, MembershipVouch
from apps.tenant_migration.admission import export_row_policy
from apps.tenant_migration.row_planning import _remap_foreign_keys
from apps.tenant_migration.target_projection import FK_POLICIES, ReferenceDisposition
from tests.data_export.portable_helpers import archive_files, csv_rows, make_job, make_space, make_user


@pytest.mark.parametrize("state, retained", [
    ("requested", False), ("invited", False), ("awaiting_vouches", False),
    ("awaiting_payment", True), ("active", True), ("revoked", True),
    ("expired", True), ("canceled", True),
])
def test_vouch_portability_matches_its_application_disposition(state, retained):
    row = SimpleNamespace(request=SimpleNamespace(state=state))
    assert export_row_policy("makerspaces.MembershipVouch", row) == (retained, retained)
    assert FK_POLICIES[("makerspaces.MembershipVouch", "request")].disposition is (
        ReferenceDisposition.REMAP_RESOLVED
    )


def test_retained_vouch_foreign_keys_remap_to_target_application_and_user():
    mappings = {
        ("makerspaces.Makerspace", 1): 101,
        ("makerspaces.MembershipRequest", 2): 102,
        ("accounts.User", 3): 103,
    }

    class Map:
        def lookup(self, model, source_pk):
            return mappings[(model._meta.label, source_pk)]

    source = {"makerspace_id": 1, "request_id": 2, "voucher_id": 3}
    row = dict(source)
    assert _remap_foreign_keys(MembershipVouch, source, row, None, Map(), None, None)
    assert row == {"makerspace_id": 101, "request_id": 102, "voucher_id": 103}


@pytest.mark.django_db(transaction=True)
def test_portable_export_excludes_open_application_vouches_and_their_voucher_identity():
    space = make_space("vouch-portable-closure")
    applicant = make_user("vouch-applicant")
    open_voucher = make_user("open-application-voucher")
    history_voucher = make_user("history-application-voucher")
    actor = make_user("vouch-export-actor")
    rows = []
    for state, voucher in (("awaiting_vouches", open_voucher), ("active", history_voucher)):
        application = MembershipRequest.objects.create(
            makerspace=space, user=applicant, kind="request", state=state,
        )
        rows.append(MembershipVouch.objects.create(
            makerspace=space, request=application, voucher=voucher,
            expires_at=timezone.now() + timedelta(days=30),
        ))
    files, _, _ = archive_files(make_job(space, actor))
    vouches = csv_rows(files, "members/membership_vouches.csv")
    assert [row["id"] for row in vouches] == [str(rows[1].pk)]
    users = {row["id"] for row in csv_rows(files, "global/users.csv")}
    assert str(open_voucher.pk) not in users
    assert str(history_voucher.pk) in users
