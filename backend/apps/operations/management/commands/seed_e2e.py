"""Seed one disposable makerspace for the Playwright suite (frontend/e2e/).

Every run creates a FRESH makerspace with a unique slug and writes its identifiers to a JSON
file the specs read, because the loan spine is built on immutable rows (scan events, evidence
rows, audit entries) that cannot be deleted to "reset" an existing one. Old e2e makerspaces
simply accumulate in a development database; CI databases are ephemeral.

Refuses to run against anything that is not a development database: `DEBUG` must be on, or
`E2E_SEED_ALLOWED=1` must be set explicitly (the CI job sets it).
"""
import json
import os
import secrets
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.backup.custody import initialize_custody_state
from apps.boxes.models import Box
from apps.hardware_requests import request_workflow
from apps.inventory.categories import ensure_default_categories
from apps.inventory.models import InventoryProduct, PublicAvailabilityMode, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.module_install import apply_profile
from apps.makerspaces.module_profiles import RECOMMENDED

DEFAULT_PASSWORD = "e2e-pass-12345"
SECRET_LOCATION = "E2E SECRET SHELF 42"
PRODUCT_NAME = "E2E Cordless Drill"
PENDING_REQUEST_FOR = "E2E robotics workshop"
PROBE_REQUEST_FOR = "E2E hard-rules probe"


class Command(BaseCommand):
    help = "Seed a fresh makerspace, staff, member, product, box and two requests for the e2e suite."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default=None, help="Makerspace slug (default: e2e-<random>).")
        parser.add_argument("--password", default=os.environ.get("E2E_PASSWORD", DEFAULT_PASSWORD))
        parser.add_argument("--write-json", default=None, help="Write the seeded identifiers here.")
        parser.add_argument("--reset", action="store_true", help="Accepted for symmetry; every run is fresh.")

    def handle(self, *args, **options):
        if not settings.DEBUG and os.environ.get("E2E_SEED_ALLOWED") != "1":
            raise CommandError(
                "seed_e2e only runs against a development database (DEBUG=True) or with "
                "E2E_SEED_ALLOWED=1 set explicitly."
            )
        token = secrets.token_hex(3)
        slug = options["slug"] or f"e2e-{token}"
        password = options["password"]
        with transaction.atomic():
            seeded = self._seed(slug, token, password)
        payload = json.dumps(seeded, indent=2)
        if options["write_json"]:
            Path(options["write_json"]).write_text(payload + "\n")
        self.stdout.write(payload)

    def _user(self, username, role, password, **flags):
        user = User.objects.create_user(
            username=username, email=f"{username}@e2e.local", password=password, role=role,
            access_status=User.AccessStatus.ACTIVE, **flags,
        )
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        return user

    def _seed(self, slug, token, password):
        superadmin = User.objects.filter(is_superuser=True).order_by("pk").first() or self._user(
            f"e2e_root_{token}", User.Role.SUPERADMIN, password, is_staff=True, is_superuser=True,
        )
        makerspace = Makerspace.objects.create(
            slug=slug, name="E2E Makerspace", location="E2E Test Bench",
            public_inventory_enabled=True, superadmin_access_enabled=True, created_by=superadmin,
        )
        initialize_custody_state(makerspace.pk)
        apply_profile(makerspace, RECOMMENDED, actor=superadmin)
        ensure_default_categories(makerspace)

        manager = self._user(f"e2e_manager_{token}", User.Role.SPACE_MANAGER, password)
        MakerspaceMembership.objects.create(
            user=manager, makerspace=makerspace, role=MakerspaceMembership.Role.SPACE_MANAGER
        )
        member = self._user(f"e2e_member_{token}", User.Role.REQUESTER, password)
        MakerspaceMembership.objects.create(
            user=member, makerspace=makerspace, role=MakerspaceMembership.Role.INVENTORY_MANAGER
        )

        box = Box.objects.create(
            makerspace=makerspace, code=f"e2ebox{token}", label="E2E Shelf A", location="E2E Test Bench",
        )
        product = InventoryProduct.objects.create(
            makerspace=makerspace, box=box, name=PRODUCT_NAME,
            description="Seeded for the end-to-end suite.", tracking_mode=TrackingMode.QUANTITY,
            total_quantity=5, available_quantity=5, is_public=True, show_public_count=True,
            public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
            storage_location=SECRET_LOCATION,
        )
        snapshot = SimpleNamespace(
            username=member.username, name="E2E Member", email=member.email, phone="",
            contact_verified=True,
        )
        pending = request_workflow.submit_request(
            makerspace, [{"product": product, "quantity": 1}], PENDING_REQUEST_FOR,
            requester_principal=member, contact_snapshot=snapshot, audit_actor=member,
        )
        probe = request_workflow.submit_request(
            makerspace, [{"product": product, "quantity": 1}], PROBE_REQUEST_FOR,
            requester_principal=member, contact_snapshot=snapshot, audit_actor=member,
        )
        request_workflow.accept_request(manager, probe)
        return {
            "slug": slug,
            "makerspace_id": makerspace.pk,
            "makerspace_name": makerspace.name,
            "manager": {"username": manager.username, "password": password},
            "member": {"username": member.username, "password": password},
            "box_code": box.code,
            "box_label": box.label,
            "product": product.name,
            "secret_location": SECRET_LOCATION,
            "pending_request_for": PENDING_REQUEST_FOR,
            "pending_request_id": pending.pk,
            "probe_request_for": PROBE_REQUEST_FOR,
            "probe_request_id": probe.pk,
        }
