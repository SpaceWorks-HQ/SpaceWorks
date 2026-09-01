import csv

import pytest

from apps.encryption.crypto import PiiUnavailable
from apps.encryption.services import rotate_dek
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.insertion_errors import (
    IdentityResolutionError,
    ImportVerificationError,
)
from apps.tenant_migration.materialization import materialize_tenant
from tests.data_export.portable_helpers import make_user, make_space
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case


pytestmark = pytest.mark.django_db(transaction=True)


def test_unresolved_identity_aborts_without_a_target_row():
    with enabled_encryption():
        user = make_user("unresolved-import")
        source = make_space("unresolved-import")
        with portable_import_case(source, user) as case:
            before = Makerspace.objects.count()
            with pytest.raises(IdentityResolutionError):
                materialize_tenant(case.root, case.job, case.carried)
            assert Makerspace.objects.count() == before
            case.job.refresh_from_db()
            assert case.job.target_makerspace_id is None


def test_decrypt_failure_rolls_back_every_materialized_row():
    with enabled_encryption():
        user = make_user("corrupt-import")
        source = make_space("corrupt-import")
        with portable_import_case(source, user, rotate=rotate_dek) as case:
            case.decide_walk_in(user)
            path = case.root / "lending" / "requests.csv"
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fields = tuple(rows[0])
            envelope = rows[0]["requester_contact_email"]
            rows[0]["requester_contact_email"] = envelope[:-1] + (
                "A" if envelope[-1] != "A" else "B"
            )
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            before = Makerspace.objects.count()

            with pytest.raises(PiiUnavailable):
                materialize_tenant(case.root, case.job, case.carried)

            assert Makerspace.objects.count() == before
            case.job.refresh_from_db()
            assert case.job.target_makerspace_id is None


def test_count_verification_failure_rolls_back(monkeypatch):
    from apps.tenant_migration import materialization

    original = materialization.verify_materialization

    def violate_count(**kwargs):
        kwargs["accounting"].imported["hardware_requests.HardwareRequest"] += 1
        return original(**kwargs)

    monkeypatch.setattr(materialization, "verify_materialization", violate_count)
    with enabled_encryption():
        user = make_user("count-import")
        source = make_space("count-import")
        with portable_import_case(source, user) as case:
            case.decide_walk_in(user)
            before = Makerspace.objects.count()
            with pytest.raises(ImportVerificationError, match="count mismatch"):
                materialize_tenant(case.root, case.job, case.carried)
            assert Makerspace.objects.count() == before


def test_blind_index_generation_verification_failure_rolls_back(monkeypatch):
    from apps.encryption.models import PiiBlindIndex, SearchKeyGeneration
    from apps.tenant_migration import materialization

    original = materialization.verify_materialization

    def violate_generation(**kwargs):
        retired = SearchKeyGeneration.objects.create(
            generation=99,
            key_fingerprint=b"x" * 32,
            status=SearchKeyGeneration.Status.RETIRED,
        )
        PiiBlindIndex.objects.filter(makerspace=kwargs["target"]).update(
            search_generation=retired
        )
        return original(**kwargs)

    monkeypatch.setattr(materialization, "verify_materialization", violate_generation)
    with enabled_encryption():
        user = make_user("generation-import")
        source = make_space("generation-import")
        with portable_import_case(source, user) as case:
            case.decide_walk_in(user)
            before = Makerspace.objects.count()
            with pytest.raises(ImportVerificationError, match="active generation"):
                materialize_tenant(case.root, case.job, case.carried)
            assert Makerspace.objects.count() == before
