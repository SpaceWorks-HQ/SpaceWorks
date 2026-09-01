from datetime import timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.models_devices import NativeAppRegistration
from apps.bookings.models import BookableSpace
from apps.events.models import Event
from apps.integrations.models import EmailTemplate
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.machines.models import Machine, MachineType
from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MemberProfile,
    MembershipRequest,
    default_enabled_modules,
)
from apps.makerspaces.roles import DEFAULT_ROLE_DEFINITIONS, MEMBER_ROLE_DEFINITION
from apps.tenant_migration.tenant_dump_bootstrap import seed_default_roles
from apps.tenant_migration.omitted_fields import FRESH, OMITTED_FIELD_RECONSTRUCTIONS
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from apps.tenant_migration.tenant_restore_target_state import (
    reconcile_native_app_registrations,
)
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused
from apps.backup.raw_projection import raw_records


pytestmark = pytest.mark.django_db


def _projected(instance):
    model = type(instance)
    source = raw_records(model.objects.filter(pk=instance.pk), model)[0]
    return sanitize_record(model, source).values


def test_makerspace_reset_values_cover_full_smtp_lifecycle_routing_and_tokens():
    archived_at = timezone.now() - timedelta(days=1)
    space = Makerspace.objects.create(
        name="D8 exact resets",
        slug="d8-exact-resets",
        membership_policy=Makerspace.MembershipPolicy.OPEN,
        referrals_enabled=True,
        superadmin_access_enabled=False,
        frontend_domain="source.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
        cors_allowed_origins=["https://source.example.test"],
        enabled_modules=["machines", "payments"],
        enabled_features={"hostile": True},
        resource_limit_overrides={"objects": 999},
        hidden_from_central_directory=True,
        storage_bytes_used=999,
        archived_at=archived_at,
        lifecycle_state=Makerspace.LifecycleState.ABORTED,
        staff_notifications_enabled=False,
        booking_requester_notifications_enabled=True,
        smtp_host="smtp.source.test",
        smtp_port=465,
        smtp_username="source-user",
        smtp_password="source-password",
        smtp_use_tls=False,
        smtp_use_ssl=True,
        smtp_from_email="source@example.test",
        telegram_group_chat_id="source-chat",
        telegram_bot_token="source-bot-token",
        slack_webhook_url="source-slack",
        mattermost_webhook_url="source-mattermost",
        discord_webhook_url="source-discord",
    )
    source_domain_token = space.domain_verification_token
    source_public_key = space.public_api_key

    values = _projected(space)

    assert {
        "membership_policy": values["membership_policy"],
        "referrals_enabled": values["referrals_enabled"],
        "superadmin_access_enabled": values["superadmin_access_enabled"],
        "frontend_domain": values["frontend_domain"],
        "frontend_domain_status": values["frontend_domain_status"],
        "domain_verified_at": values["domain_verified_at"],
        "frontend_domain_changed_at": values["frontend_domain_changed_at"],
        "cors_allowed_origins": values["cors_allowed_origins"],
        "enabled_modules": values["enabled_modules"],
        "enabled_features": values["enabled_features"],
        "resource_limit_overrides": values["resource_limit_overrides"],
        "hidden_from_central_directory": values["hidden_from_central_directory"],
        "storage_bytes_used": values["storage_bytes_used"],
        "archived_at": values["archived_at"],
        "archived_by_id": values["archived_by_id"],
        "lifecycle_state": values["lifecycle_state"],
        "staff_notifications_enabled": values["staff_notifications_enabled"],
        "booking_requester_notifications_enabled": values[
            "booking_requester_notifications_enabled"
        ],
    } == {
        "membership_policy": "request", "referrals_enabled": False,
        "superadmin_access_enabled": True, "frontend_domain": None,
        "frontend_domain_status": "pending", "domain_verified_at": None,
        "frontend_domain_changed_at": None, "cors_allowed_origins": [],
        "enabled_modules": default_enabled_modules(),
        "enabled_features": default_enabled_features(),
        "resource_limit_overrides": {}, "hidden_from_central_directory": False,
        "storage_bytes_used": 0, "archived_at": None, "archived_by_id": None,
        "lifecycle_state": "importing", "staff_notifications_enabled": True,
        "booking_requester_notifications_enabled": False,
    }
    assert (
        values["smtp_host"], values["smtp_port"], values["smtp_username"],
        values["smtp_password"], values["smtp_use_tls"], values["smtp_use_ssl"],
        values["smtp_from_email"],
    ) == ("", 587, "", "", True, False, "")
    assert values["telegram_group_chat_id"] == ""
    assert values["telegram_bot_token"] == ""
    assert values["slack_webhook_url"] == ""
    assert values["mattermost_webhook_url"] == ""
    assert values["discord_webhook_url"] == ""
    assert values["domain_verification_token"] != source_domain_token
    assert values["public_api_key"] != source_public_key


def test_membership_history_preserves_but_all_grants_and_delivery_reset():
    space = Makerspace.objects.create(name="D8 membership", slug="d8-membership")
    role = MakerspaceRole.objects.create(
        makerspace=space, name="Source authority", slug="source-authority",
        granted_actions=["manage_makerspace"],
    )
    user = User.objects.create_user(username="d8-membership-user")
    when = timezone.now() - timedelta(days=2)
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
        status="revoked",
        receives_notifications=False,
        can_refer=False,
        can_verify=True,
        verified_at=when,
        activated_at=when,
        revoked_at=when,
        revocation_reason="source history",
    )

    values = _projected(membership)

    assert values["status"] == "revoked"
    assert values["verified_at"] == when
    assert values["activated_at"] == when
    assert values["revoked_at"] == when
    assert values["revocation_reason"] == "source history"
    assert values["role"] == MakerspaceMembership.Role.CUSTOM
    assert values["assigned_role_id"] is None
    assert values["can_refer"] is True
    assert values["can_verify"] is False
    assert values["receives_notifications"] is True


def test_closed_membership_request_keeps_history_but_cannot_auto_activate():
    space = Makerspace.objects.create(name="D8 closed request", slug="d8-closed-request")
    user = User.objects.create_user(username="d8-closed-request-user")
    role = space.roles.first()
    request = MembershipRequest.objects.create(
        makerspace=space,
        user=user,
        kind=MembershipRequest.Kind.REQUEST,
        state=MembershipRequest.State.REVOKED,
        assigned_role=role,
        auto_activate_on_claim=True,
        decision_note="historical decision",
    )

    values = _projected(request)

    assert values["state"] == MembershipRequest.State.REVOKED
    assert values["decision_note"] == "historical decision"
    assert values["assigned_role_id"] is None
    assert values["auto_activate_on_claim"] is False


def test_visibility_consent_template_and_checkout_values_are_exact():
    space = Makerspace.objects.create(
        name="D8 preserved disclosure", slug="d8-preserved-disclosure",
        public_inventory_enabled=False, public_stats_enabled=True,
        public_stats_show_holder_names=True,
        public_print_status_lookup_policy=Makerspace.PublicPrintStatusLookupPolicy.EMAIL_UNVERIFIED,
    )
    product = InventoryProduct.objects.create(
        makerspace=space, name="D8 product", is_public=False,
        show_public_count=True, public_availability_mode="hidden", is_archived=True,
        public_self_checkout_enabled=True,
    )
    asset = InventoryAsset.objects.create(
        makerspace=space, product=product, asset_tag="D8-PROJECTION",
        public_self_checkout_enabled=True,
    )
    machine_type = MachineType.objects.create(makerspace=space, slug="d8-type", name="D8 type")
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="D8 machine",
        is_public=False, is_active=False,
    )
    bookable = BookableSpace.objects.create(
        makerspace=space, name="D8 room", is_public=True,
        show_public_availability=True, show_public_booker_names=True,
        is_active=False, approval_mode=BookableSpace.ApprovalMode.INSTANT,
        requester_notifications_enabled=True,
    )
    event = Event.objects.create(
        makerspace=space, title="D8 event", starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(hours=1), is_public=True,
        status=Event.Status.PUBLISHED,
    )
    user = User.objects.create_user(username="d8-profile-values")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user)
    profile = MemberProfile.objects.create(
        membership=membership, is_visible=True, show_attended_events=True,
        headline="preserved headline",
    )
    template = EmailTemplate.objects.create(
        makerspace=space, stream=EmailTemplate.Stream.HARDWARE,
        audience=EmailTemplate.Audience.STAFF, key="accepted", subject="Tenant subject",
        text_body="Tenant body", html_body="<p>Tenant body</p>", is_active=False,
    )

    assert tuple(_projected(space)[field] for field in (
        "public_inventory_enabled", "public_stats_enabled",
        "public_stats_show_holder_names", "public_print_status_lookup_policy",
    )) == (False, True, True, "email_unverified")
    assert tuple(_projected(product)[field] for field in (
        "is_public", "show_public_count", "public_availability_mode",
        "is_archived", "public_self_checkout_enabled",
    )) == (False, True, "hidden", True, False)
    assert _projected(asset)["public_self_checkout_enabled"] is False
    assert tuple(_projected(machine)[field] for field in ("is_public", "is_active")) == (False, False)
    assert tuple(_projected(bookable)[field] for field in (
        "is_public", "show_public_availability", "show_public_booker_names",
        "is_active", "approval_mode", "requester_notifications_enabled",
    )) == (True, True, True, False, "approve", None)
    assert tuple(_projected(event)[field] for field in ("is_public", "status")) == (True, "published")
    assert tuple(_projected(profile)[field] for field in (
        "is_visible", "show_attended_events", "headline",
    )) == (True, True, "preserved headline")
    assert tuple(_projected(template)[field] for field in (
        "subject", "text_body", "html_body", "is_active",
    )) == ("Tenant subject", "Tenant body", "<p>Tenant body</p>", False)


def test_target_native_apps_and_default_roles_equal_target_configuration():
    space = Makerspace.objects.create(name="D8 target authority", slug="d8-target-authority")
    NativeAppRegistration.objects.create(
        makerspace=space, platform="apple", app_id="source.app",
        environment="production", verifier_config_key="source.app",
        status=NativeAppRegistration.Status.APPROVED,
    )
    with pytest.raises(TenantRestoreRefused, match="tenant-scoped native-app authority survived"):
        reconcile_native_app_registrations(
            configured_apps={"apple": {"target.app": {"environments": ["production"]}}}
        )

    NativeAppRegistration.objects.filter(makerspace=space).delete()
    assert reconcile_native_app_registrations(
        configured_apps={"apple": {"target.app": {"environments": ["development", "production"]}}}
    ) == (
        ("apple", "target.app", "development", "target.app"),
        ("apple", "target.app", "production", "target.app"),
    )
    space.roles.all().delete()
    role_ids = seed_default_roles("default", space.pk)
    expected_slugs = {
        *(parts[3] if len(parts) > 3 else parts[0] for parts in DEFAULT_ROLE_DEFINITIONS),
        MEMBER_ROLE_DEFINITION[3],
    }
    assert set(role_ids) == expected_slugs
    assert set(space.roles.values_list("slug", "is_default", "is_protected")) == {
        (slug, True, True) for slug in expected_slugs
    }


def test_every_public_or_status_token_is_reconstructed_with_a_fresh_value():
    token_edges = {
        edge for edge, disposition in OMITTED_FIELD_RECONSTRUCTIONS.items()
        if disposition is FRESH
    }
    assert token_edges
    for model_label, field_name in token_edges:
        field = apps.get_model(model_label)._meta.get_field(field_name)
        assert field.has_default() and callable(field.default)
        assert field.get_default() != field.get_default()
