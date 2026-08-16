import csv

import pytest

from apps.accounts.models import User
from apps.encryption.crypto import parse_envelope
from apps.encryption.services import rotate_dek
from apps.events.models import EventRegistration
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.tenant_migration.materialization import materialize_tenant
from tests.data_export.portable_helpers import make_user, make_space
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case


pytestmark = pytest.mark.django_db(transaction=True)


def _archived_request_envelope(root):
    path = root / "lending" / "requests.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return next(csv.DictReader(handle))["requester_contact_email"]


def test_portable_archive_round_trips_into_a_new_tenant_with_target_aad():
    with enabled_encryption():
        source_user = make_user("materialize-source")
        source = make_space("materialize-source")
        with portable_import_case(source, source_user, rotate=rotate_dek) as case:
            case.decide_walk_in(source_user)
            source_envelope = _archived_request_envelope(case.root)

            result = materialize_tenant(
                case.root,
                case.job,
                case.carried,
                target_identity={"name": "Imported Lab", "slug": "imported-lab"},
                batch_size=2,
            )

        target = Makerspace.objects.get(pk=result.target_makerspace_id)
        imported = HardwareRequest.objects.get(makerspace=target)
        target_envelope = HardwareRequest.objects.filter(pk=imported.pk).values_list(
            "requester_contact_email", flat=True
        ).get()
        assert imported.requester_contact_email == "member@example.test"
        assert imported.requester_name == "Archive Member"
        assert parse_envelope(target_envelope)[0] == parse_envelope(source_envelope)[0] == 1
        assert target.encryption_keys.get(status="active").version == 2
        assert EventRegistration.objects.get(event__makerspace=target).email == "member@example.test"
        membership = MakerspaceMembership.objects.get(makerspace=target)
        assert membership.assigned_role == target.roles.get(slug="member")
        assert membership.user.is_walk_in is True


def test_linked_target_superadmin_is_reported_not_rejected():
    with enabled_encryption():
        source_user = User.objects.create_superuser(
            username="linked-import-superadmin",
            email="linked-import-superadmin@example.test",
            password="pw",
        )
        source = make_space("linked-superadmin-source")
        with portable_import_case(source, source_user) as case:
            case.decide_link(source_user, source_user)
            result = materialize_tenant(
                case.root,
                case.job,
                case.carried,
                target_identity={"slug": "linked-superadmin-target"},
            )

        assert result.identities_linked == 1
        assert result.preexisting_global_authority == (
            {
                "source_user_id": str(source_user.pk),
                "target_user_id": source_user.pk,
                "kind": "target_global_superadmin",
            },
        )
        assert User.objects.get(pk=source_user.pk).is_superuser is True
