"""Certification extras: the card print field, the profile opt-in and the coverage report."""
import pytest
from django.utils import timezone

from apps.machines.certifications import live_certification_names
from apps.machines.models import CertificationGrant, CertificationType, MachineType
from apps.machines.reports_certifications import build_certification_coverage
from apps.makerspaces import member_card_printing, member_card_services, member_card_templates, profile_services
from apps.makerspaces.member_card_views import snapshot_for
from apps.makerspaces.models import MakerspaceMembership
from apps.operations.org_report_scope import EXCLUDED_ORGANIZATION_REPORT_KEYS
from apps.operations.report_registry import REPORT_REGISTRY
from tests.return_helpers import make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def _setup(slug):
    space = make_space(slug)
    manager = make_member(f"{slug}-manager", space)
    user = make_user(f"{slug}-member", access_status="active")
    membership = MakerspaceMembership.objects.create(user=user, makerspace=space, role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    machine_type = MachineType.objects.create(makerspace=space, slug=f"{slug}-laser", name="Laser")
    live = CertificationType.objects.create(makerspace=space, machine_type=machine_type, name="Laser induction")
    stale = CertificationType.objects.create(makerspace=space, machine_type=machine_type, name="Old induction")
    CertificationGrant.objects.create(certification_type=live, membership=membership)
    CertificationGrant.objects.create(certification_type=stale, membership=membership, revoked_at=timezone.now())
    return space, manager, membership


def test_live_names_and_card_print_field():
    space, manager, membership = _setup("cx-card")
    assert live_certification_names(membership) == ("Laser induction",)
    card = member_card_services.issue_card(manager, membership, printed_name="Cert Holder")
    snapshot = snapshot_for(card)
    assert snapshot.certifications == ("Laser induction",)
    assert member_card_printing._field_value(snapshot, "certifications") == "Laser induction"
    template = member_card_templates.normalize_template({"front_fields": ["printed_name", "certifications"]})
    assert member_card_printing.render_cards_pdf(template, [snapshot], title="t").startswith(b"%PDF")


def test_profile_publishes_certifications_only_after_opt_in():
    space, manager, membership = _setup("cx-profile")
    before = profile_services.read_profile(membership, include_activity=False)
    assert before["show_certifications"] is False and before["certifications"] == []
    profile_services.save_profile(membership, {"show_certifications": True})
    after = profile_services.read_profile(membership, include_activity=False)
    assert after["show_certifications"] is True and after["certifications"] == ["Laser induction"]


def test_certification_coverage_report_row_and_org_exclusion():
    space, manager, membership = _setup("cx-report")
    result = build_certification_coverage(space.id)
    assert result.field_order == REPORT_REGISTRY["certification-coverage"].fields
    rows = {row["certification_type"]: row for row in result.records}
    assert rows["Laser induction"]["certified_members"] == 1
    assert rows["Laser induction"]["active_members"] == 2  # manager + member
    assert rows["Laser induction"]["coverage_percent"] == 50.0
    assert rows["Old induction"] == {**rows["Old induction"], "certified_members": 0, "revoked_grants": 1}
    assert rows["Laser induction"]["gating_enabled"] is False
    assert "certification-coverage" in EXCLUDED_ORGANIZATION_REPORT_KEYS
