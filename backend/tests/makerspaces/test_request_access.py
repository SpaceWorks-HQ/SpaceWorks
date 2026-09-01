"""The membership / account-less-requests pair is impossible, at every depth.

`RequestSubmitView` takes its anonymous branch BEFORE any membership guard runs, so a
makerspace carrying both `membership` and `anonymous_requests_enabled` would let a
stranger walk past the membership requirement the operator had just switched on. These
pin the three enforcement depths independently, because each one covers writers the
others do not: the model rule covers every save, the service covers the deliberate
operator request, and the view re-derives so a row written behind both still fails closed.
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import install_module, uninstall_module
from apps.makerspaces.request_access import (
    ACCOUNTS,
    ANYONE,
    MEMBERS,
    RequestAccessConflict,
    effective_policy,
    set_anonymous_requests,
)

pytestmark = pytest.mark.django_db


def _space(slug, *, modules, anonymous=False):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=list(modules),
        anonymous_requests_enabled=anonymous,
    )


CORE_PLUS = ["public_inventory", "request_workflow", "staff_admin", "scanner",
             "evidence_uploads", "qr_management"]


# --------------------------------------------------------------------------- model


def test_saving_with_membership_forces_account_less_requests_off():
    space = _space("ra-model", modules=[*CORE_PLUS, "membership"], anonymous=True)

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is False
    assert effective_policy(space) == MEMBERS


def test_a_partial_save_cannot_leave_the_impossible_pair_on_the_row():
    """`save(update_fields=[...])` that does not name the flag must still persist it."""
    space = _space("ra-partial", modules=CORE_PLUS, anonymous=True)
    assert space.anonymous_requests_enabled is True

    space.enabled_modules = [*CORE_PLUS, "membership"]
    space.save(update_fields=["enabled_modules"])

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is False


def test_membership_off_leaves_account_less_requests_alone():
    space = _space("ra-open", modules=CORE_PLUS, anonymous=True)

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is True
    assert effective_policy(space) == ANYONE


def test_policy_without_membership_and_without_the_flag_is_accounts():
    space = _space("ra-accounts", modules=CORE_PLUS)
    assert effective_policy(space) == ACCOUNTS


# ------------------------------------------------------------------- module install


def test_installing_membership_closes_account_less_requests():
    space = _space("ra-install", modules=CORE_PLUS, anonymous=True)

    install_module(space, "membership")

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is False


def test_the_forced_close_is_audited_with_the_before_and_after_policy():
    """The flip happens inside `Makerspace.save()`, which has no actor, so it is audited on
    the module-change path instead. Without this the capability meta carries module and
    feature lists only -- which cannot distinguish a previous `anyone` policy from
    `accounts` -- and the operator loses the record that installing membership closed an
    unauthenticated write surface."""
    space = _space("ra-forced-audit", modules=CORE_PLUS, anonymous=True)

    install_module(space, "membership")

    entry = AuditLog.objects.filter(action="makerspace.capabilities_changed").latest("id")
    assert entry.meta["request_access"] == {"before": ANYONE, "after": MEMBERS}


def test_installing_membership_records_the_accounts_to_members_move_too():
    """Not only the forced-off case: installing membership moves `accounts` -> `members`
    even when account-less requests were already off, and that is still a change in who
    may submit."""
    space = _space("ra-accounts-to-members", modules=CORE_PLUS)

    install_module(space, "membership")

    entry = AuditLog.objects.filter(action="makerspace.capabilities_changed").latest("id")
    assert entry.meta["request_access"] == {"before": ACCOUNTS, "after": MEMBERS}


def test_an_unrelated_module_change_records_no_policy_meta():
    """The key is omitted rather than emitted-as-unchanged, so an auditor reading the log
    sees a request-access entry only where the policy actually moved."""
    space = _space("ra-unrelated-audit", modules=CORE_PLUS)

    install_module(space, "telegram")

    entry = AuditLog.objects.filter(action="makerspace.capabilities_changed").latest("id")
    assert "request_access" not in entry.meta


def test_uninstalling_membership_does_not_reopen_account_less_requests():
    """Forcing off is one-way. Re-opening an unauthenticated write surface is an
    explicit operator act, never a side effect of removing an unrelated module."""
    space = _space("ra-uninstall", modules=[*CORE_PLUS, "membership", "member_accounts"])

    uninstall_module(space, "membership")

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is False
    assert effective_policy(space) == ACCOUNTS


# ------------------------------------------------------------------------- service


def test_set_anonymous_requests_refuses_while_membership_is_installed():
    space = _space("ra-refuse", modules=[*CORE_PLUS, "membership"])

    with pytest.raises(RequestAccessConflict):
        set_anonymous_requests(space, True)

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is False


def test_set_anonymous_requests_audits_the_policy_change():
    space = _space("ra-audit", modules=CORE_PLUS)

    resulting = set_anonymous_requests(space, True)

    assert resulting == ANYONE
    entry = AuditLog.objects.filter(action="makerspace.request_access_changed").latest("id")
    assert entry.meta["before"] == ACCOUNTS
    assert entry.meta["after"] == ANYONE


def test_setting_the_same_value_twice_writes_no_second_audit_row():
    space = _space("ra-idempotent", modules=CORE_PLUS)
    set_anonymous_requests(space, True)
    before = AuditLog.objects.filter(action="makerspace.request_access_changed").count()

    set_anonymous_requests(space, True)

    assert AuditLog.objects.filter(action="makerspace.request_access_changed").count() == before


# ------------------------------------------------------------------------- command


def test_command_reports_the_policy_the_module_state_actually_produces():
    space = _space("ra-cmd-accounts", modules=CORE_PLUS)
    out = StringIO()

    call_command("set_request_access", "--makerspace", space.slug, "--mode", MEMBERS, stdout=out)

    text = out.getvalue()
    # `members` was asked for, but without the membership module the honest answer is
    # `accounts`, and the operator must be told rather than left believing otherwise.
    assert "signed-in account" in text
    assert "You asked for 'members'" in text


def test_command_refuses_anyone_when_membership_is_installed():
    space = _space("ra-cmd-conflict", modules=[*CORE_PLUS, "membership"])

    with pytest.raises(CommandError):
        call_command("set_request_access", "--makerspace", space.slug, "--mode", ANYONE)

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is False


def test_list_modules_json_reports_installed_keys_and_request_access():
    space = _space("ra-json", modules=CORE_PLUS, anonymous=True)
    out = StringIO()

    call_command("list_modules", "--makerspace", space.slug, "--json", stdout=out)

    payload = json.loads(out.getvalue())
    assert payload["makerspace"] == space.slug
    assert payload["request_access"] == ANYONE
    assert "request_workflow" in payload["installed"]


# ---------------------------------------------------------------------------- view


def test_an_anonymous_submission_is_refused_when_membership_is_installed():
    """The hole this closes: the row carries BOTH, written behind the model rule."""
    space = _space("ra-view", modules=[*CORE_PLUS, "membership"])
    # Straight to the column, bypassing save() exactly as raw SQL or an old restore would.
    Makerspace.objects.filter(pk=space.pk).update(anonymous_requests_enabled=True)
    product = InventoryProduct.objects.create(
        makerspace=space, name="Multimeter", total_quantity=2, available_quantity=2, is_public=True,
    )

    response = APIClient().post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {
            "contact_name": "Stranger",
            "contact_email": "stranger@example.test",
            "items": [{"product_id": product.id, "quantity": 1}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="ra-view-key",
    )

    assert response.status_code == 401


# --------------------------------------------------------------- /control/ matrix


def test_the_control_capability_matrix_audits_the_forced_policy_change():
    """The `/control/` matrix does NOT go through `module_install._apply` -- the admin
    mixin saves the model directly -- so it needs its own before/after capture. The model
    still forces account-less requests off, but module and feature lists alone cannot tell
    an `anyone -> members` change from an `accounts -> members` one.
    """
    from types import SimpleNamespace

    from django.contrib.admin import ModelAdmin
    from django.contrib.admin.sites import AdminSite

    from apps.accounts.models import User
    from apps.makerspaces.admin_capabilities import (
        MakerspaceAdminForm,
        MakerspaceCapabilityAdminMixin,
    )

    class _CapabilityAdmin(MakerspaceCapabilityAdminMixin, ModelAdmin):
        """The mixin relies on `super().save_model`, so it needs a real ModelAdmin."""

    space = _space("ra-control-matrix", modules=CORE_PLUS, anonymous=True)
    assert effective_policy(space) == ANYONE

    form = MakerspaceAdminForm(instance=space)
    # Captured from the unmodified instance, before `clean_capabilities` rewrites it.
    assert form.request_access_before == ANYONE

    actor = User.objects.create_user(username="ra-control-actor", is_superuser=True)
    space.enabled_modules = [*CORE_PLUS, "membership", "member_accounts"]
    admin = _CapabilityAdmin(Makerspace, AdminSite())
    admin.save_model(SimpleNamespace(user=actor), space, form, change=True)

    space.refresh_from_db()
    assert space.anonymous_requests_enabled is False
    entry = AuditLog.objects.filter(action="makerspace.capabilities_changed").latest("id")
    assert entry.meta["request_access"] == {"before": ANYONE, "after": MEMBERS}
