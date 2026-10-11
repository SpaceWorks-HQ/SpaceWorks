"""Fixtures shared by pack contract and HTTP tests."""
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


def person(name, *, superadmin=False):
    actor = User.objects.create_user(username=name, email=f"{name}@example.test", password="password",
                                     role=User.Role.SUPERADMIN if superadmin else User.Role.REQUESTER)
    actor.email_verified_at = timezone.now()
    actor.save(update_fields=["email_verified_at"])
    return actor


def space(slug, *, manager=None):
    row = Makerspace.objects.create(name=slug, slug=slug)
    row.enabled_features = list(set(row.enabled_features or []) | {"packs.import"})
    row.save(update_fields=["enabled_features"])
    manager = manager or person(f"{slug}-manager")
    MakerspaceMembership.objects.create(makerspace=row, user=manager,
        assigned_role=MakerspaceRole.objects.get(makerspace=row, slug="space_manager"))
    return row, manager


def client(actor=None):
    api = APIClient()
    if actor:
        api.force_authenticate(actor)
    return api


def seed_configuration(row, actor):
    from apps.integrations.email_templates_registry import REGISTRY
    from apps.integrations.models import ChatTemplate, EmailTemplate, NotificationPreference, EmailNotificationMute
    from apps.integrations import notification_rules
    from apps.inventory.models import Category, InventoryProduct
    from apps.makerspaces.models import MembershipPlan
    from apps.makerspaces.membership_admission_settings import update_settings
    from apps.makerspaces.loan_policy_settings import update_loan_policy
    from apps.makerspaces.role_services import create_role
    from apps.makerspaces.waiver_services import publish_waiver
    from apps.bookings.models import BookableSpace
    create_role(makerspace=row, actor=actor, name="Front Desk", granted_actions=["issue_request", "return_request"])
    publish_waiver(actor, row, "Use tools safely and follow staff instructions.", "starter-v1")
    category = Category.objects.create(makerspace=row, name="Tools", slug="tools", loan_days=5)
    InventoryProduct.objects.create(makerspace=row, name="Drill", description="Cordless drill", category=category,
        total_quantity=9, available_quantity=7, issued_quantity=2, storage_location="PRIVATE-SHELF")
    plan = MembershipPlan.objects.create(makerspace=row, name="Monthly", interval="monthly", amount=12, currency="usd")
    update_settings(actor, row, {"join_mode": "approval", "default_plan": plan})
    update_loan_policy(actor, row, {"default_loan_days": 14, "loan_max_items": 3})
    BookableSpace.objects.create(makerspace=row, name="Meeting Room", booking_lead_time_minutes=120)
    key, entry = next((key, entry) for key, entry in REGISTRY.items() if key[0:2] == ("hardware", "staff"))
    EmailTemplate.objects.create(makerspace=row, stream=key[0], audience=key[1], key=key[2],
        subject=entry.default_subject, text_body=entry.default_text, html_body=entry.default_html)
    ChatTemplate.objects.create(makerspace=row, feature="hardware_requests", event=key[2], text_body=entry.default_text)
    NotificationPreference.objects.create(makerspace=row, feature="hardware_requests", channel="email", enabled=False)
    event = notification_rules.EVENT_CATALOG[("hardware", "requester")][0]
    EmailNotificationMute.objects.create(makerspace=row, target="requester", stream="hardware", event=event, audience="requester")
    row.refresh_from_db()
