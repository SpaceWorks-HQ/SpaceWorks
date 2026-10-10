"""The tenant payment control form records only changed field names, atomically."""

from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.audit.models import AuditLog
from apps.payments.admin import MakerspacePaymentSettingsAdmin, MakerspacePaymentSettingsAdminForm
from apps.payments.models import MakerspacePaymentSettings
from tests.return_helpers import make_space
from tests.test_subdomain_approval import make_superadmin

pytestmark = pytest.mark.django_db


def test_control_payment_settings_change_records_actor_scope_and_field_names():
    space = make_space("payment-control-audit")
    row = MakerspacePaymentSettings.objects.create(makerspace=space)
    root = make_superadmin("payment-control-audit-root")
    form = MakerspacePaymentSettingsAdminForm(instance=row, data={
        "makerspace": space.pk, "stripe_publishable_key": "pk_changed",
        "stripe_secret_key": "sk_control_secret", "stripe_webhook_secret": "whsec_control_secret",
        "default_currency": "usd",
    })
    assert form.is_valid(), form.errors
    request = RequestFactory().post("/control/")
    request.user = root
    MakerspacePaymentSettingsAdmin(MakerspacePaymentSettings, admin.site).save_model(request, row, form, True)
    entry = AuditLog.objects.get(action="payments.settings_updated", target_id=str(row.pk))
    assert entry.actor == root and entry.makerspace_id == space.pk
    assert entry.meta["via"] == "control"
    assert "stripe_secret_key" in entry.meta["changed_fields"]
    assert "sk_control_secret" not in str(entry.meta)
    assert "whsec_control_secret" not in str(entry.meta)


def test_audit_failure_rolls_back_the_credential_update(monkeypatch):
    space = make_space("payment-control-atomic")
    row = MakerspacePaymentSettings.objects.create(makerspace=space)
    request = RequestFactory().post("/control/")
    request.user = make_superadmin("payment-control-atomic-root")
    form = SimpleNamespace(
        changed_data=["default_currency"],
        payment_setting_changes=lambda: {"default_currency": "eur"},
    )

    def fail(*a, **k):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.payments.admin.audit.record", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        MakerspacePaymentSettingsAdmin(MakerspacePaymentSettings, admin.site).save_model(request, row, form, True)
    row.refresh_from_db()
    assert row.default_currency == "usd"
