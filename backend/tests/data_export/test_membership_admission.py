"""Admission evidence is private tenant content, with portable identity closure."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.utils import timezone

from apps.accounts.models import User
from apps.data_export.archive import project_row, transform_value
from apps.data_export.datasets import DATASETS, DATASET_SPECS
from apps.data_export.guards import validate_all
from apps.data_export.types import Fidelity, Redacted
from apps.encryption.crypto import is_envelope
from apps.encryption.registry import fields_for_label
from apps.makerspaces.models import (
    Makerspace, MakerspaceMembershipSettings, MembershipPlan, MembershipRequest,
    MembershipVouch,
)
from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from apps.tenant_migration.tenant_dump_source_projection import (
    _close_conditional_rows, _source_row_allowed,
)
from apps.tenant_migration.tenant_dump_user_rows import apply_user_closure
from tests.encryption.conftest import enabled_encryption


def test_admission_models_and_user_edges_have_complete_export_classification():
    validate_all()
    for label in (
        "makerspaces.MembershipRequest", "makerspaces.MakerspaceMembershipSettings",
        "makerspaces.MembershipVouch",
    ):
        model = apps.get_model(label)
        assert FIRST_PARTY_FIELD_NAMES[label] == {
            field.name for field in model._meta.fields
        }


def test_admission_dataset_refuses_foreign_plan_or_request():
    request = DATASET_SPECS["makerspaces.MembershipRequest"][1]
    assert request.includes({"makerspace": 1, "selected_plan__makerspace": 1, "admission_payment__makerspace": 1}, 1)
    assert not request.includes({"makerspace": 1, "selected_plan__makerspace": 2, "admission_payment__makerspace": 1}, 1)
    assert not request.includes({"makerspace": 1, "selected_plan__makerspace": 1, "admission_payment__makerspace": 2}, 1)
    settings = DATASET_SPECS["makerspaces.MakerspaceMembershipSettings"][1]
    assert settings.includes({"makerspace": 1, "default_plan__makerspace": 1}, 1)
    assert settings.includes({"makerspace": 1, "default_plan__makerspace": None}, 1)
    assert not settings.includes({"makerspace": 1, "default_plan__makerspace": 2}, 1)
    vouch = DATASET_SPECS["makerspaces.MembershipVouch"][1]
    assert not vouch.includes({"makerspace": 1, "request__makerspace": 2}, 1)


@pytest.mark.django_db
def test_application_export_queryset_excludes_foreign_plan_and_payment_edges():
    from apps.payments.models import Payment

    local = Makerspace.objects.create(name="Local export", slug="local-admission-export")
    foreign = Makerspace.objects.create(name="Foreign export", slug="foreign-admission-export")
    applicant = User.objects.create_user(username="export-edge-applicant")
    row = MembershipRequest.objects.create(makerspace=local, user=applicant, kind="request", state="requested")
    predicate = DATASET_SPECS["makerspaces.MembershipRequest"][1].as_q(local.pk)
    assert MembershipRequest.objects.filter(predicate, pk=row.pk).exists()
    plan = MembershipPlan.objects.create(makerspace=foreign, name="Foreign plan", interval="monthly")
    MembershipRequest.objects.filter(pk=row.pk).update(selected_plan=plan)
    assert not MembershipRequest.objects.filter(predicate, pk=row.pk).exists()
    other = MembershipRequest.objects.create(makerspace=foreign, user=applicant, kind="request", state="requested")
    payment = Payment.objects.create(makerspace=foreign, member=applicant, subject_type="membership_request",
                                     subject_id=other.pk, amount="5", currency="usd", provider="unclaimed")
    MembershipRequest.objects.filter(pk=row.pk).update(selected_plan=None, admission_payment=payment)
    assert not MembershipRequest.objects.filter(predicate, pk=row.pk).exists()
    MembershipRequest.objects.filter(pk=row.pk).update(admission_payment=None)
    assert MembershipRequest.objects.filter(predicate, pk=row.pk).exists()


def test_readable_export_redacts_application_free_text():
    answers = json.dumps({"answers": [
        {"id": "why", "type": "paragraph", "value": "My private circumstances"},
        {"id": "experience", "type": "single_choice", "value": "beginner"},
    ]})
    value = transform_value(
        "makerspaces.MembershipRequest", "application_answers",
        Redacted("custom_answers_redacted"), answers,
    )
    assert value["answers"][0]["value"] == "[REDACTED_FREE_TEXT]"
    assert value["answers"][1]["value"] == "beginner"


@pytest.mark.parametrize("raw", ["not JSON", '["personal details"]'])
def test_unrecognized_application_answers_fail_closed_in_readable_export(raw):
    value = transform_value(
        "makerspaces.MembershipRequest", "application_answers",
        Redacted("custom_answers_redacted"), raw,
    )
    assert value == {"custom_answers_redacted": True}


def test_unpaid_application_transports_as_canceled_history_with_its_charge():
    model = MembershipRequest
    row = {
        field.attname: field.get_default() if field.has_default() else None
        for field in model._meta.fields
    }
    row.update(id=11, makerspace_id=1, state="awaiting_payment", user_id=9,
               admission_managed=True, admission_payment_id=12, first_term_amount="25.00")
    projected = sanitize_record(model, row)
    assert projected.values["state"] == "canceled"
    assert projected.values["admission_managed"] is False
    assert projected.values["admission_payment_id"] == 12
    assert projected.values["first_term_amount"] == "25.00"


def test_unapproved_application_and_vouches_cannot_transfer_admission_authority():
    assert not _source_row_allowed(
        "makerspaces.MembershipRequest", {"state": "awaiting_vouches"}, 1, None,
    )
    assert _source_row_allowed(
        "makerspaces.MembershipRequest", {"state": "awaiting_payment"}, 1, None,
    )
    rows = {
        "makerspaces.MembershipRequest": ({"id": 1},),
        "makerspaces.MembershipVouch": (
            {"id": 2, "request_id": 1}, {"id": 3, "request_id": 9},
        ),
    }
    _close_conditional_rows(rows)
    assert rows["makerspaces.MembershipVouch"] == ({"id": 2, "request_id": 1},)


def test_stub_applicant_answers_are_removed_without_decryption():
    rows = {"makerspaces.MembershipRequest": (
        {"id": 1, "user_id": 7, "application_answers": "private ciphertext"},
        {"id": 2, "user_id": 8, "application_answers": "tenant ciphertext"},
    )}
    result = apply_user_closure(rows, SimpleNamespace(stubbed_user_ids={7}))
    assert result["makerspaces.MembershipRequest"][0]["application_answers"] is None
    assert result["makerspaces.MembershipRequest"][1]["application_answers"] == "tenant ciphertext"


@pytest.mark.django_db(transaction=True)
def test_application_answers_encrypt_and_readable_export_decrypts_then_redacts():
    space = Makerspace.objects.create(name="Private admissions", slug="private-admissions")
    user = User.objects.create_user(username="private-applicant")
    answer = json.dumps({"answers": [
        {"id": "why", "type": "paragraph", "value": "Sensitive application"},
    ]})
    assert {field.field_name for field in fields_for_label("makerspaces.MembershipRequest")} == {
        "application_answers",
    }
    with enabled_encryption():
        application = MembershipRequest.objects.create(
            makerspace=space, user=user, kind="request", state="requested",
            application_answers=answer,
        )
        application.refresh_from_db()
        assert is_envelope(application.__dict__["application_answers"])
        assert application.application_answers == answer
        dataset = DATASETS[(Fidelity.REDACTED, "members/membership_requests.csv")]
        projected = project_row(dataset, application, set())
        assert "Sensitive application" not in projected["application_answers"]


@pytest.mark.django_db(transaction=True)
def test_membership_purge_removes_admission_evidence_but_preserves_core_members():
    from apps.makerspaces.models import MakerspaceMembership
    from apps.makerspaces.module_purge import purge_module

    space = Makerspace.objects.create(name="Admission purge", slug="admission-purge")
    user = User.objects.create_user(username="purge-applicant")
    actor = User.objects.create_superuser(username="admission-purge-admin")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user)
    plan = MembershipPlan.objects.create(makerspace=space, name="Default", amount=10, interval="monthly")
    MakerspaceMembershipSettings.objects.update_or_create(
        makerspace=space, defaults={"default_plan": plan},
    )
    application = MembershipRequest.objects.create(
        makerspace=space, user=user, kind="request", state="active", selected_plan=plan,
        application_answers='{"answers": []}',
    )
    MembershipVouch.objects.create(
        makerspace=space, request=application, voucher=user,
        expires_at=timezone.now() + timedelta(days=30),
    )
    purge_module(space, "membership", actor)
    assert MakerspaceMembership.objects.filter(pk=membership.pk).exists()
    assert not MembershipRequest.objects.filter(makerspace=space).exists()
    assert not MembershipVouch.objects.filter(makerspace=space).exists()
    assert not MakerspaceMembershipSettings.objects.filter(makerspace=space).exists()
    assert not MembershipPlan.objects.filter(makerspace=space).exists()
