"""F3 catalog, privacy, transaction and delivery contracts."""

from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts import rbac
from apps.integrations import notify
from apps.integrations.chat_templates import chat_entry, validate_chat_template_string
from apps.integrations.email_templates_registry import get_entry, validate_email_template_strings
from apps.integrations.email_templates_registry_research import FAMILY_EVENTS, REQUESTER_EVENTS
from apps.integrations.models import EmailLog, NotificationChannel, NotificationFeature, NotificationPreference
from apps.integrations.notification_catalog import DEFAULT_CHANNEL_STATE, FEATURE_EVENTS
from apps.integrations.recipients_selection import FEATURE_MODULES, SELECTABLE_FEATURES
from apps.integrations.staff_notifications import staff_emails_for_feature, staff_user_ids_for_feature
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment
from apps.payments.notifications import notify_payment
from tests.module_helpers import disable_module
from tests.return_helpers import make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def family_world(slug):
    space = make_space(slug)
    space.enabled_modules = sorted(set(space.enabled_modules) | {
        "payments", "membership", "procurement", "machines", "maintenance",
    })
    space.save(update_fields=["enabled_modules", "updated_at"])
    manager = make_member(f"{slug}-manager", space)
    member = make_member(f"{slug}-member", space, membership_role=MakerspaceMembership.Role.CUSTOM)
    payment = Payment.objects.create(
        makerspace=space, member=member, created_by=manager, subject_type="makerspace_membership",
        subject_id=MakerspaceMembership.objects.get(makerspace=space, user=member).pk,
        amount="9876.54", currency="usd", provider="unclaimed",
    )
    return space, manager, member, payment


def capture_delivery(monkeypatch):
    emails, channels = [], []
    monkeypatch.setattr(notify, "dispatch_email", lambda **kw: emails.append(kw) or
                        SimpleNamespace(status=EmailLog.Status.SENT))
    monkeypatch.setattr(notify, "dispatch_channel", lambda **kw: channels.append(kw) or [])
    return emails, channels


def test_catalog_extends_stable_families_with_external_channels_off_and_personal_inbox_on():
    assert set(FEATURE_EVENTS) == set(NotificationFeature.values)
    assert set(DEFAULT_CHANNEL_STATE) == set(NotificationFeature.values)
    assert {"request_pending", "member_joined"} <= set(FEATURE_EVENTS["members"])
    assert {"schedule_created", "schedule_updated", "schedule_deactivated", "logged",
            "schedule_completed"} <= set(FEATURE_EVENTS["maintenance"])
    for stream, events in FAMILY_EVENTS.items():
        feature = "members" if stream == "membership" else stream
        assert set(events) <= set(FEATURE_EVENTS[feature])
        assert feature in SELECTABLE_FEATURES and feature in FEATURE_MODULES
        assert set(DEFAULT_CHANNEL_STATE[feature]) == set(NotificationChannel.values)
        assert DEFAULT_CHANNEL_STATE[feature]["in_app"] is True
        assert not any(enabled for channel, enabled in DEFAULT_CHANNEL_STATE[feature].items() if channel != "in_app")
    assert DEFAULT_CHANNEL_STATE["hardware_requests"]["email"] is True
    assert DEFAULT_CHANNEL_STATE["bookings"]["telegram"] is True


def test_templates_validate_and_requester_coverage_is_explicit():
    for stream, events in FAMILY_EVENTS.items():
        feature = "members" if stream == "membership" else stream
        for event in events:
            staff = get_entry(stream, "staff", event)
            assert staff is chat_entry(feature, event)
            validate_email_template_strings(stream, "staff", event,
                                            staff.default_subject, staff.default_text, "")
            validate_chat_template_string(feature, event, staff.default_text)
            own = get_entry(stream, "requester", event)
            assert bool(own) == (event in REQUESTER_EVENTS.get(stream, ()))
            if own:
                validate_email_template_strings(stream, "requester", event,
                                                own.default_subject, own.default_text, "")
            fields = {field["name"] for field in staff.fields}
            assert not any(word in field for field in fields
                           for word in ("email", "phone", "token", "secret", "amount", "currency"))
    with pytest.raises(ValidationError):
        validate_chat_template_string("payments", "charge_raised", "{% invalid %}")


def test_payment_is_on_commit_and_snapshot_has_no_provider_or_amount(monkeypatch, django_capture_on_commit_callbacks):
    space, _staff, _member, payment = family_world("f3-snapshot")
    observed = []
    monkeypatch.setattr(notify, "_run_guarded", lambda ms, feature, event, build, sync, occurred_at=None, event_key=None:
                        observed.append((event, build())))
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "charge_raised")
        payment.status = "paid_online"
        assert observed == []
    event, payload = observed[0]
    assert event == "charge_raised" and payload.context["subject"].status == "pending"
    assert vars(payload.context["subject"]) == {"id": payment.pk, "status": "pending", "_frozen": True}
    assert payload.data == {"payment_id": payment.pk, "refund_id": None}
    assert "9876.54" not in payload.text


def test_rollback_sends_nothing(monkeypatch, django_capture_on_commit_callbacks):
    _space, _staff, _member, payment = family_world("f3-rollback")
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                notify_payment(payment, "charge_raised")
                raise RuntimeError("rollback")
    assert callbacks == [] and emails == [] and channels == []


def test_default_off_sends_nothing(monkeypatch, django_capture_on_commit_callbacks):
    _space, _staff, _member, payment = family_world("f3-default")
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "charge_raised")
    assert emails == [] and channels == []


def test_member_variant_uses_own_address_and_amount_never_reaches_chat(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, member, payment = family_world("f3-address")
    foreign = make_user("f3-foreign")
    emails, channels = capture_delivery(monkeypatch)
    for channel in ("email", "telegram"):
        NotificationPreference.objects.create(makerspace=space, feature="payments", channel=channel, enabled=True)
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "payment_received")
    staff = [e for e in emails if e["audience"] == "staff"]
    own = [e for e in emails if e["audience"] == "requester"]
    assert [e["to_email"] for e in staff] == [manager.email]
    assert [e["to_email"] for e in own] == [member.email]
    assert "9876.54" in own[0]["text_body"]
    assert foreign.email not in [e["to_email"] for e in emails]
    assert len(channels) == 1 and "9876.54" not in channels[0]["text_body"]
    assert channels[0]["payload"]["payment_id"] == payment.pk
    assert "amount" not in channels[0]["payload"]


@pytest.mark.parametrize("status,opt_out", [("revoked", False), ("active", True)])
def test_member_opt_out_and_revocation_win(monkeypatch, django_capture_on_commit_callbacks, status, opt_out):
    space, _staff, member, payment = family_world(f"f3-opt-{status}")
    MakerspaceMembership.objects.filter(makerspace=space, user=member).update(
        status=status, receives_notifications=not opt_out,
    )
    NotificationPreference.objects.create(makerspace=space, feature="payments", channel="email", enabled=True)
    emails, _channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "payment_received")
    assert not any(e["audience"] == "requester" for e in emails)


def test_account_only_payment_owner_can_receive_own_email(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, _member, _payment = family_world("f3-account")
    owner = make_user("f3-account-owner", access_status="active")
    from apps.hardware_requests.models import HardwareRequest
    loan = HardwareRequest.objects.create(makerspace=space, requester=owner, requester_username=owner.username)
    payment = Payment.objects.create(makerspace=space, member=owner, created_by=manager, subject_type="loan_deposit",
                                     subject_id=loan.pk, amount="5.00", currency="usd")
    NotificationPreference.objects.create(makerspace=space, feature="payments", channel="email", enabled=True)
    emails, _channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "charge_raised")
    assert [e["to_email"] for e in emails if e["audience"] == "requester"] == [owner.email]


def test_selected_members_get_staff_body_and_requester_flag_controls_own_variant(monkeypatch, django_capture_on_commit_callbacks):
    from apps.integrations.models_recipients import NotificationRecipient
    space, _manager, member, payment = family_world("f3-selection")
    NotificationPreference.objects.create(makerspace=space, feature="payments", channel="email", enabled=True)
    NotificationRecipient.objects.create(makerspace=space, feature="payments", event="charge_raised", kind="members")
    emails, _channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "charge_raised")
    assert emails and all(e["audience"] == "staff" and "9876.54" not in e["text_body"] for e in emails)
    emails.clear()
    NotificationRecipient.objects.create(makerspace=space, feature="payments", event="charge_raised", kind="requester")
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "charge_raised")
    assert [e["to_email"] for e in emails if e["audience"] == "requester"] == [member.email]


def test_provider_failure_does_not_escape_on_commit(monkeypatch, django_capture_on_commit_callbacks):
    space, _manager, _member, payment = family_world("f3-provider-failure")
    NotificationPreference.objects.create(makerspace=space, feature="payments", channel="email", enabled=True)
    def fail(**_kwargs):
        raise RuntimeError("Provider unavailable")
    monkeypatch.setattr(notify, "dispatch_email", fail)
    with django_capture_on_commit_callbacks(execute=True):
        result = notify_payment(payment, "charge_raised")
        assert result.scheduled


def test_ledger_notifications_survive_rail_removal_before_commit(monkeypatch, django_capture_on_commit_callbacks):
    space, _staff, _member, payment = family_world("f3-module")
    NotificationPreference.objects.create(makerspace=space, feature="payments", channel="email", enabled=True)
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        notify_payment(payment, "charge_raised")
        disable_module(space, "payments")
    assert emails and channels == []


def test_finance_fallback_matches_existing_finance_list_action():
    from tests.rbac_f6_helpers import custom_actor

    space, manager, _member, _payment = family_world("f3-finance")
    make_member("f3-inventory", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    treasurer = custom_actor(space, [rbac.Action.VIEW_FINANCE], "treasurer")
    custom_actor(space, [rbac.Action.RECORD_PAYMENT], "cashier")
    assert staff_emails_for_feature(space, "payments", event="charge_raised") == [manager.email, treasurer.email]
    assert staff_user_ids_for_feature(space, "payments", event="charge_raised") == [manager.pk, treasurer.pk]
    from apps.integrations.staff_notifications import _FEATURE_ACTIONS
    assert _FEATURE_ACTIONS["payments"] == rbac.Action.VIEW_FINANCE


def test_choice_migration_matches_all_runtime_fields():
    migration = import_module("apps.integrations.migrations.0028_research_notification_families").Migration
    assert migration.dependencies == [("integrations", "0027_device_notifications")]
    assert len(migration.operations) == 5
    for operation in migration.operations:
        runtime = apps.get_model("integrations", operation.model_name)._meta.get_field(operation.name)
        assert list(operation.field.choices) == list(runtime.choices)
        assert operation.field.max_length == runtime.max_length


@pytest.mark.parametrize("stream", ["stock", "certifications", "maintenance", "membership"])
def test_new_template_stream_module_off_is_400(stream):
    from rest_framework.exceptions import ValidationError as ApiValidationError
    from apps.admin_api.views_email_templates_common import _resolve_makerspace, STREAM_MODULES
    space, manager, _member, _payment = family_world(f"f3-template-{stream}")
    disable_module(space, STREAM_MODULES[stream])
    with pytest.raises(ApiValidationError) as error:
        _resolve_makerspace(manager, space.pk, stream)
    assert error.value.status_code == 400


def test_payment_templates_remain_available_without_online_rail():
    from apps.admin_api.views_email_templates_common import _resolve_makerspace
    space, manager, _, _ = family_world("f3-ledger-templates")
    disable_module(space, "payments")
    assert _resolve_makerspace(manager, space.pk, "payments").pk == space.pk
