import csv

import pytest

from apps.accounts.models import User
from apps.boxes.models import QrCode, QrScanEvent
from apps.encryption.crypto import parse_envelope
from apps.encryption.services import rotate_dek
from apps.events.models import EventRegistration
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItemAsset,
    PublicToolLoan,
)
from apps.inventory.models import InventoryAsset
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipRequest
from apps.operations.models import InventoryAdjustment, StockTransfer, StockTransferLine
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.models import ExternalTenantReference
from tests.data_export.portable_helpers import make_user, make_space
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.row_closure_helpers import create_row_closure_scenario


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


def test_row_closure_dispositions_round_trip_without_live_foreign_ids():
    with enabled_encryption():
        source_user = make_user("row-closure-roundtrip")
        source = make_space("row-closure-roundtrip")
        with portable_import_case(
            source,
            source_user,
            prepare_source=create_row_closure_scenario,
        ) as case:
            case.decide_walk_in(source_user)
            scenario = case.source_data
            result = materialize_tenant(
                case.root,
                case.job,
                case.carried,
                target_identity={"slug": "row-closure-target"},
                batch_size=2,
            )

        target = Makerspace.objects.get(pk=result.target_makerspace_id)
        imported_request = HardwareRequest.objects.get(makerspace=target)
        present_asset = InventoryAsset.objects.get(
            makerspace=target,
            asset_tag="STAYS-HERE",
        )
        present_link = HardwareRequestItemAsset.objects.get(
            request_item__request=imported_request
        )
        assert present_link.asset == present_asset
        assert not InventoryAsset.objects.filter(
            makerspace=target,
            asset_tag="MOVED-AWAY",
        ).exists()
        assert result.dropped["hardware_requests.HardwareRequestItemAsset"] == 1
        moved_link_ref = ExternalTenantReference.objects.get(
            makerspace=target,
            source_model_label="hardware_requests.HardwareRequestItemAsset",
            source_object_id=str(scenario.moved_link.pk),
            field_name="asset",
        )
        assert moved_link_ref.target_model_label == "hardware_requests.HardwareRequestItem"
        assert moved_link_ref.target_object_id == str(present_link.request_item_id)

        moved_adjustment = InventoryAdjustment.objects.get(
            makerspace=target,
            reason="Moved asset history",
        )
        blank_adjustment = InventoryAdjustment.objects.get(
            makerspace=target,
            reason="Originally no asset",
        )
        assert moved_adjustment.asset_id is None
        assert blank_adjustment.asset_id is None
        moved_asset_ref = ExternalTenantReference.objects.get(
            makerspace=target,
            source_model_label="operations.InventoryAdjustment",
            source_object_id=str(scenario.moved_adjustment.pk),
            field_name="asset",
        )
        assert moved_asset_ref.target_model_label == "operations.InventoryAdjustment"
        assert moved_asset_ref.target_object_id == str(moved_adjustment.pk)
        # Scoped by model label as well as id: a source pk is unique only WITHIN a
        # model, so an unscoped filter matches an unrelated model's row of the same
        # id and reports provenance that was never written for this adjustment.
        assert not ExternalTenantReference.objects.filter(
            makerspace=target,
            source_model_label="operations.InventoryAdjustment",
            source_object_id=str(scenario.blank_adjustment.pk),
            field_name="asset",
        ).exists()

        imported_qr = QrCode.objects.get(makerspace=target)
        assert imported_qr.target_type == QrCode.TargetType.ASSET
        assert imported_qr.target_id == present_asset.pk
        assert imported_qr.payload != scenario.present_qr.payload
        assert result.regenerated[("boxes.QrCode", "payload")] == 1
        assert not QrScanEvent.objects.filter(makerspace=target).exists()
        rebound_ref = ExternalTenantReference.objects.get(
            makerspace=target,
            source_model_label="boxes.QrCode",
            source_object_id=str(scenario.rebound_qr.pk),
            field_name="target_type+target_id",
        )
        assert rebound_ref.target_model_label == ""
        assert rebound_ref.target_object_id == ""
        scan_ref = ExternalTenantReference.objects.get(
            makerspace=target,
            source_model_label="boxes.QrScanEvent",
            source_object_id=str(scenario.rebound_scan.pk),
            field_name="qr_code",
        )
        assert scan_ref.target_model_label == "hardware_requests.HardwareRequest"
        assert scan_ref.target_object_id == str(imported_request.pk)
        assert result.dropped["boxes.QrCode"] == 1
        assert result.dropped["boxes.QrScanEvent"] == 1

        loan = PublicToolLoan.objects.get(makerspace=target)
        assert loan.asset_ids == [present_asset.pk]
        assert loan.qr_ids == [imported_qr.pk]
        assert loan.qr_code == imported_qr
        assert loan.target_id == present_asset.pk

        assert not StockTransfer.objects.filter(
            destination_makerspace=target,
            reason="Inbound from another owner",
        ).exists()
        assert not StockTransferLine.objects.filter(
            transfer__destination_makerspace=target,
            notes="Foreign-owned line",
        ).exists()
        inbound_adjustment = InventoryAdjustment.objects.get(
            makerspace=target,
            reason="Inbound adjustment",
        )
        assert inbound_adjustment.transfer_id is None
        inbound_ref = ExternalTenantReference.objects.get(
            makerspace=target,
            source_model_label="operations.InventoryAdjustment",
            source_object_id=str(scenario.inbound_adjustment.pk),
            field_name="transfer",
        )
        assert inbound_ref.target_object_id == str(inbound_adjustment.pk)
        for source_object in (scenario.inbound_transfer, scenario.inbound_line):
            provenance = ExternalTenantReference.objects.get(
                makerspace=target,
                source_model_label=source_object._meta.label,
                source_object_id=str(source_object.pk),
                field_name="inbound_transfer",
            )
            assert provenance.target_model_label == ""
            assert provenance.target_object_id == ""
        assert result.dropped["operations.StockTransfer"] == 1
        assert result.dropped["operations.StockTransferLine"] == 1

        imported_membership_request = MembershipRequest.objects.get(makerspace=target)
        assert imported_membership_request.state == MembershipRequest.State.ACTIVE
        assert imported_membership_request.assigned_role == target.roles.get(slug="member")
        assert not MembershipRequest.objects.filter(
            makerspace=target,
            state=MembershipRequest.State.INVITED,
        ).exists()
        assert result.dropped["makerspaces.MembershipRequest"] == 1
        assert result.external_references_created == ExternalTenantReference.objects.filter(
            makerspace=target,
            source_archive_digest=case.job.source_archive_digest,
        ).count()


def test_noncolliding_qr_payload_is_preserved_byte_for_byte():
    with enabled_encryption():
        source_user = make_user("qr-preserved")
        source = make_space("qr-preserved")
        with portable_import_case(
            source,
            source_user,
            prepare_source=create_row_closure_scenario,
        ) as case:
            case.decide_walk_in(source_user)
            archived_payload = case.source_data.present_qr.payload
            QrCode.objects.filter(pk=case.source_data.present_qr.pk).update(
                payload="source-label-moved-after-snapshot"
            )
            result = materialize_tenant(
                case.root,
                case.job,
                case.carried,
                target_identity={"slug": "qr-preserved-target"},
            )

        imported = QrCode.objects.get(makerspace_id=result.target_makerspace_id)
        assert imported.payload == archived_payload
        assert result.preserved[("boxes.QrCode", "payload")] == 1
        assert result.regenerated[("boxes.QrCode", "payload")] == 0


def test_colliding_qr_payload_is_regenerated_without_touching_existing_row():
    with enabled_encryption():
        source_user = make_user("qr-collision")
        source = make_space("qr-collision")
        with portable_import_case(
            source,
            source_user,
            prepare_source=create_row_closure_scenario,
        ) as case:
            case.decide_walk_in(source_user)
            archived_payload = case.source_data.present_qr.payload
            QrCode.objects.filter(pk=case.source_data.present_qr.pk).update(
                payload="source-label-released-for-collision"
            )
            survivor_space = make_space("qr-collision-survivor")
            survivor = QrCode.objects.create(
                makerspace=survivor_space,
                payload=archived_payload,
                target_type=QrCode.TargetType.BOX,
                target_id=1,
                created_by=source_user,
            )
            result = materialize_tenant(
                case.root,
                case.job,
                case.carried,
                target_identity={"slug": "qr-collision-target"},
            )

        imported = QrCode.objects.get(makerspace_id=result.target_makerspace_id)
        survivor.refresh_from_db()
        assert imported.payload != archived_payload
        assert survivor.payload == archived_payload
        assert result.regenerated[("boxes.QrCode", "payload")] == 1
        assert result.preserved[("boxes.QrCode", "payload")] == 0
