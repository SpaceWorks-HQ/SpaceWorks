"""Transactional round trips, previews, policy validation and failure rollback."""
from copy import deepcopy
import json

import pytest
from django.apps import apps
from apps.audit.models import AuditLog
from apps.data_export.space_pack_configuration import SECTIONS
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import MakerspaceRole, MakerspaceLoanPolicy, MakerspaceMembershipSettings
from apps.makerspaces.space_pack_export import export_pack
from apps.makerspaces.space_pack_format import PackConflict, PackError, seal
from apps.makerspaces.space_pack_services import apply_pack, preview_pack
from .space_pack_helpers import seed_configuration, space

pytestmark = pytest.mark.django_db(transaction=True)


def counts():
    return {spec.model: apps.get_model(spec.model).objects.count() for spec in SECTIONS.values()} | {"audit": AuditLog.objects.count()}


def test_round_trip_all_configuration_sections_and_idempotent_apply():
    source, actor = space("pack-source")
    target, _ = space("pack-target", manager=actor)
    seed_configuration(source, actor)
    pack = export_pack(actor, source)
    preview = preview_pack(actor, target, pack)
    assert preview["applied"] is False
    apply_pack(actor, target, pack, base_checksum=preview["base_checksum"])
    target.refresh_from_db()
    assert export_pack(actor, target) == pack
    product = InventoryProduct.objects.get(makerspace=target, name="Drill")
    assert product.total_quantity == product.available_quantity == product.issued_quantity == 0
    assert product.storage_location == "" and product.box_id is None
    second = preview_pack(actor, target, pack)
    assert second["changes"] == []
    assert AuditLog.objects.filter(makerspace=target, action="makerspace.space_pack_applied", actor=actor).exists()


@pytest.mark.parametrize("provisioned_settings", [True, False])
def test_dry_run_never_creates_rows_or_audits_or_updates_timestamps(provisioned_settings):
    source, actor = space("pack-dry-source")
    target, _ = space("pack-dry-target", manager=actor)
    if not provisioned_settings:
        MakerspaceMembershipSettings.objects.filter(makerspace=target).delete()
    seed_configuration(source, actor)
    pack = export_pack(actor, source)
    before = counts()
    # New spaces have an unconfigured admission row; legacy spaces may not.
    # A preview must preserve every stored field in either case.
    before_rows = {
        spec.model: list(apps.get_model(spec.model).objects.order_by("pk").values())
        for spec in SECTIONS.values()
    }
    timestamp = target.updated_at
    preview = preview_pack(actor, target, pack)
    assert preview["changes"]
    target.refresh_from_db()
    assert target.updated_at == timestamp and counts() == before
    assert not MakerspaceLoanPolicy.objects.filter(makerspace=target).exists()
    for model, rows in before_rows.items():
        assert list(apps.get_model(model).objects.order_by("pk").values()) == rows
    assert MakerspaceMembershipSettings.objects.filter(makerspace=target).exists() is provisioned_settings


def test_atomic_failure_rolls_back_configuration_roles_and_every_audit(monkeypatch):
    from apps.makerspaces import space_pack_services as services
    source, actor = space("pack-fail-source")
    target, _ = space("pack-fail-target", manager=actor)
    seed_configuration(source, actor)
    pack = export_pack(actor, source)
    preview = preview_pack(actor, target, pack)
    before = counts()
    original = services.write_section
    calls = []
    def fail_second(*args):
        calls.append(args[2])
        if len(calls) == 2:
            raise RuntimeError("injected domain failure")
        return original(*args)
    monkeypatch.setattr(services, "write_section", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        apply_pack(actor, target, pack, base_checksum=preview["base_checksum"])
    assert len(calls) == 2
    target.refresh_from_db()
    assert counts() == before and target.default_loan_days != 14
    assert not MakerspaceRole.objects.filter(makerspace=target, name="Front Desk").exists()


def test_stale_preview_and_missing_preview_refused_without_changes():
    source, actor = space("pack-stale-source")
    target, _ = space("pack-stale-target", manager=actor)
    pack = export_pack(actor, source)
    preview = preview_pack(actor, target, pack)
    target.public_inventory_enabled = not target.public_inventory_enabled
    target.save(update_fields=["public_inventory_enabled"])
    before = counts()
    with pytest.raises(PackConflict):
        apply_pack(actor, target, pack, base_checksum=preview["base_checksum"])
    with pytest.raises(PackError):
        apply_pack(actor, target, pack)
    assert counts() == before


def test_no_members_money_credentials_evidence_or_history_in_export():
    row, actor = space("pack-private")
    seed_configuration(row, actor)
    row.telegram_group_chat_id = "PRIVATE-CHAT"
    row.smtp_username = "PRIVATE-SMTP"
    row.save(update_fields=["telegram_group_chat_id", "smtp_username"])
    from apps.payments.models import Payment
    from apps.makerspaces.models import MakerspaceMembership
    membership = MakerspaceMembership.objects.get(makerspace=row, user=actor)
    Payment.objects.create(makerspace=row, member=actor, created_by=actor,
        subject_type="makerspace_membership", subject_id=membership.pk,
        subject_label="PRIVATE-DEBT", amount="98765.43", currency="usd", provider="unclaimed")
    from apps.evidence.models import EvidencePhoto
    EvidencePhoto.objects.create(makerspace=row, uploaded_by=actor, evidence_type="issue",
        object_key="PRIVATE-EVIDENCE", content_type="image/jpeg", size_bytes=123)
    from apps.audit import services as audit
    audit.record(actor, "test.pack_private_history", makerspace=row, meta={"sentinel": "PRIVATE-AUDIT"})
    text = json.dumps(export_pack(actor, row))
    for sentinel in (actor.email, actor.username, "PRIVATE-SHELF", "PRIVATE-CHAT", "PRIVATE-SMTP",
                     "PRIVATE-DEBT", "98765.43", "PRIVATE-EVIDENCE", "PRIVATE-AUDIT"):
        assert sentinel not in text


@pytest.mark.parametrize("field", ["total_quantity", "box", "storage_location", "member", "object_key"])
def test_unknown_item_template_fields_are_rejected_before_apply(field):
    row, actor = space(f"pack-fields-{field}")
    seed_configuration(row, actor)
    config = deepcopy(export_pack(actor, row)["configuration"])
    config["item_templates"][0][field] = "forbidden"
    before = counts()
    with pytest.raises(PackError):
        preview_pack(actor, row, seal(config))
    assert counts() == before


def test_invalid_booking_bounds_and_missing_references_are_rejected_in_preview():
    row, actor = space("pack-invalid")
    seed_configuration(row, actor)
    config = deepcopy(export_pack(actor, row)["configuration"])
    config["booking_rules"][0]["max_booking_duration_minutes"] = 1
    with pytest.raises(PackError):
        preview_pack(actor, row, seal(config))
    config = deepcopy(export_pack(actor, row)["configuration"])
    config["item_templates"][0]["category"] = "foreign-category"
    with pytest.raises(PackError):
        preview_pack(actor, row, seal(config))


def test_duplicate_product_names_refuse_export_and_unrelated_rows_survive_import():
    row, actor = space("pack-duplicates")
    InventoryProduct.objects.create(makerspace=row, name="Duplicate")
    InventoryProduct.objects.create(makerspace=row, name="Duplicate")
    with pytest.raises(PackError):
        export_pack(actor, row)
    source, _ = space("pack-additive-source", manager=actor)
    target, _ = space("pack-additive-target", manager=actor)
    existing = InventoryProduct.objects.create(makerspace=target, name="Retained", total_quantity=4, available_quantity=4)
    pack = export_pack(actor, source)
    preview = preview_pack(actor, target, pack)
    apply_pack(actor, target, pack, base_checksum=preview["base_checksum"])
    existing.refresh_from_db()
    assert existing.total_quantity == existing.available_quantity == 4


@pytest.mark.parametrize("mode", ["vouch", "closed"])
def test_admission_mode_and_disabled_feature_gates_survive_idempotent_import(mode):
    from apps.makerspaces.membership_admission_settings import update_settings
    source, actor = space(f"pack-admission-{mode}")
    target, _ = space(f"pack-admission-target-{mode}", manager=actor)
    update_settings(actor, source, {"join_mode": mode})
    source.refresh_from_db()
    source.enabled_features = [key for key in source.enabled_features
                               if key not in {"membership.vouching", "membership.application_form"}]
    source.save(update_fields=["enabled_features"])
    pack = export_pack(actor, source)
    for destination in (target, target, source):
        preview = preview_pack(actor, destination, pack)
        apply_pack(actor, destination, pack, base_checksum=preview["base_checksum"])
        destination.refresh_from_db()
        assert export_pack(actor, destination) == pack
        assert MakerspaceMembershipSettings.objects.get(makerspace=destination).join_mode == mode


def test_existing_waiver_version_cannot_be_overwritten_or_reactivated():
    from apps.makerspaces.waiver_services import publish_waiver
    row, actor = space("pack-waiver-history")
    publish_waiver(actor, row, "First version", "v1")
    publish_waiver(actor, row, "Current version", "v2")
    before = counts()
    config = deepcopy(export_pack(actor, row)["configuration"])
    config["active_waiver"] = {"version": "v1", "body": "First version"}
    with pytest.raises(PackError):
        preview_pack(actor, row, seal(config))
    config["active_waiver"] = {"version": "v2", "body": "Rewritten liability"}
    with pytest.raises(PackError):
        preview_pack(actor, row, seal(config))
    assert counts() == before


def test_export_omits_retained_notification_channels_with_modules_off():
    from apps.integrations.models import NotificationPreference
    row, actor = space("pack-retained-channel")
    NotificationPreference.objects.create(makerspace=row, feature="hardware_requests", channel="telegram", enabled=True)
    row.enabled_modules = [key for key in row.enabled_modules if key != "telegram"]
    row.save(update_fields=["enabled_modules"])
    pack = export_pack(actor, row)
    assert pack["configuration"]["notification_defaults"] == []
    assert preview_pack(actor, row, pack)["changes"] == []


def test_template_whitespace_and_empty_email_bodies_round_trip():
    from apps.integrations.models import EmailTemplate, ChatTemplate
    source, actor = space("pack-template-source")
    target, _ = space("pack-template-target", manager=actor)
    seed_configuration(source, actor)
    EmailTemplate.objects.filter(makerspace=source).update(subject="", text_body="", html_body="")
    ChatTemplate.objects.filter(makerspace=source).update(text_body="  Staff notice\n\n")
    pack = export_pack(actor, source)
    preview = preview_pack(actor, target, pack)
    apply_pack(actor, target, pack, base_checksum=preview["base_checksum"])
    target.refresh_from_db()
    assert export_pack(actor, target) == pack


@pytest.mark.parametrize("section,field,value", [
    ("settings", "public_inventory_enabled", "false"),
    ("opening_hours", "timezone", " UTC "),
])
def test_preview_refuses_field_coercion_that_would_hide_actual_written_values(section, field, value):
    row, actor = space(f"pack-coercion-{section}")
    config = deepcopy(export_pack(actor, row)["configuration"])
    config[section][field] = value
    before = counts()
    with pytest.raises(PackError):
        preview_pack(actor, row, seal(config))
    assert counts() == before


def test_explicit_default_loan_policy_is_distinct_from_unconfigured_legacy_defaults():
    from apps.makerspaces.loan_policy_settings import update_loan_policy
    source, actor = space("pack-default-policy-source")
    target, _ = space("pack-default-policy-target", manager=actor)
    assert export_pack(actor, target)["configuration"]["loan_policy"] is None
    update_loan_policy(actor, source, {})
    pack = export_pack(actor, source)
    assert pack["configuration"]["loan_policy"] is not None
    preview = preview_pack(actor, target, pack)
    assert any(change["section"] == "loan_policy" for change in preview["changes"])
    apply_pack(actor, target, pack, base_checksum=preview["base_checksum"])
    assert MakerspaceLoanPolicy.objects.filter(makerspace=target).exists()
