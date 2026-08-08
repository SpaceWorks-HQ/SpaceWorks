from django.conf import settings
from django.core.management.base import BaseCommand
from decimal import Decimal

from apps.accounts.models import User
from apps.apiclients.models import ApiClient
from apps.boxes.models import Box
from apps.inventory.categories import ensure_default_categories
from apps.inventory.models import (
    Category,
    InventoryAsset,
    InventoryProduct,
    PublicAvailabilityMode,
    TrackingMode,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.module_install import apply_profile
from apps.makerspaces.module_profiles import EVERYTHING
from apps.machines.models import Machine, MachineConsumablePool, MachineServiceRequest, MachineType
from apps.machines.service_workflow import submit as submit_service_request


DEMO_SPACES = [
    {
        "slug": "alpha-lab",
        "name": "Alpha Robotics Lab",
        "location": "Main Campus - Room A12",
        "manager": "alpha_manager",
        "superadmin_access_enabled": True,
    },
    {
        "slug": "beta-workshop",
        "name": "Beta Woodshop",
        "location": "North Wing - Woodshop",
        "manager": "beta_manager",
        "superadmin_access_enabled": False,
    },
    {
        "slug": "gamma-fab",
        "name": "Gamma Fabrication Studio",
        "location": "Downtown Fab Studio",
        "manager": "gamma_manager",
        "superadmin_access_enabled": True,
    },
]

DEMO_PRODUCTS = [
    ("Arduino Uno R4", "microcontrollers", 18, "Electronics Bay"),
    ("Soldering Station", "accessories", 6, "Repair Bench"),
    ("Cordless Drill Kit", "accessories", 4, "Tool Wall"),
    ("Digital Caliper", "sensors", 10, "Measurement Drawer"),
]


class Command(BaseCommand):
    help = "Seed demo superadmin, makerspaces, staff, boxes, and inventory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="demo12345",
            help="Password applied to all demo staff accounts.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        superadmin = self._user(
            "superadmin",
            "superadmin@makerspace.local",
            password,
            User.Role.SUPERADMIN,
            is_staff=True,
            is_superuser=True,
        )

        spaces_created = 0
        products_written = 0
        assets_written = 0
        machine_services_written = 0
        for spec in DEMO_SPACES:
            makerspace, created = Makerspace.objects.update_or_create(
                slug=spec["slug"],
                defaults={
                    "name": spec["name"],
                    "location": spec["location"],
                    "public_inventory_enabled": True,
                    "superadmin_access_enabled": spec["superadmin_access_enabled"],
                    "created_by": superadmin,
                },
            )
            spaces_created += int(created)
            # Modules are opt-in, so a freshly created makerspace starts core-only and
            # the machine-service seed below would hit `require_module` and abort the
            # whole command. The demo data spans every module, so seed the `everything`
            # profile - but only on creation, so a re-run never rewrites the module set
            # of a space the operator has since tuned.
            if created:
                apply_profile(makerspace, EVERYTHING, actor=superadmin)
            ensure_default_categories(makerspace)
            manager = self._user(
                spec["manager"],
                f"{spec['manager']}@makerspace.local",
                password,
                User.Role.SPACE_MANAGER,
            )
            MakerspaceMembership.objects.update_or_create(
                makerspace=makerspace,
                user=manager,
                defaults={"role": MakerspaceMembership.Role.SPACE_MANAGER},
            )
            box = self._box(makerspace, "Starter Inventory", spec["location"])
            products_written += self._products(makerspace, box)
            assets_written += self._assets(makerspace, box)
            machine_services_written += self._machine_service(makerspace, manager)

        self._sync_legacy_hmac_client()
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded demo data: "
                f"spaces_created={spaces_created}, "
                f"products_written={products_written}, "
                f"assets_written={assets_written}, "
                f"machine_services_written={machine_services_written}. "
                "Accounts: superadmin, alpha_manager, beta_manager, gamma_manager."
            )
        )
        self.stdout.write(self.style.WARNING(f"Demo password for all accounts: {password}"))

    def _user(self, username, email, password, role, **flags):
        user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
        user.email = email
        user.role = role
        user.access_status = User.AccessStatus.ACTIVE
        user.must_change_password = False
        user.is_staff = flags.get("is_staff", role == User.Role.SUPERADMIN)
        user.is_superuser = flags.get("is_superuser", role == User.Role.SUPERADMIN)
        user.set_password(password)
        user.save(
            update_fields=[
                "email",
                "role",
                "access_status",
                "must_change_password",
                "is_staff",
                "is_superuser",
                "password",
            ]
        )
        return user

    def _box(self, makerspace, label, location):
        box, _ = Box.objects.update_or_create(
            makerspace=makerspace,
            label=label,
            defaults={"location": location, "description": "Seeded demo storage."},
        )
        return box

    def _products(self, makerspace, box):
        categories = {
            category.slug: category
            for category in Category.objects.filter(makerspace=makerspace)
        }
        for name, category_slug, quantity, location in DEMO_PRODUCTS:
            InventoryProduct.objects.update_or_create(
                makerspace=makerspace,
                name=name,
                defaults={
                    "box": box,
                    "category": categories.get(category_slug),
                    "description": f"Demo stock for {makerspace.name}.",
                    "tracking_mode": TrackingMode.QUANTITY,
                    "total_quantity": quantity,
                    "available_quantity": quantity,
                    "reserved_quantity": 0,
                    "issued_quantity": 0,
                    "damaged_quantity": 0,
                    "lost_quantity": 0,
                    "needs_fix_quantity": 0,
                    "is_public": True,
                    "public_self_checkout_enabled": True,
                    "show_public_count": True,
                    "public_availability_mode": PublicAvailabilityMode.EXACT_COUNT,
                    "storage_location": location,
                    "is_archived": False,
                },
            )
        return len(DEMO_PRODUCTS)

    def _assets(self, makerspace, box):
        product, _ = InventoryProduct.objects.update_or_create(
            makerspace=makerspace,
            name="Oscilloscope Rigol DS1054Z",
            defaults={
                "box": box,
                "description": "Serialized demo lab instrument.",
                "tracking_mode": TrackingMode.INDIVIDUAL,
                "total_quantity": 3,
                "available_quantity": 3,
                "reserved_quantity": 0,
                "issued_quantity": 0,
                "damaged_quantity": 0,
                "lost_quantity": 0,
                "needs_fix_quantity": 0,
                "is_public": True,
                "public_self_checkout_enabled": False,
                "show_public_count": False,
                "public_availability_mode": PublicAvailabilityMode.STATUS_ONLY,
                "storage_location": "Instrument Cabinet",
                "is_archived": False,
            },
        )
        for index in range(1, 4):
            InventoryAsset.objects.update_or_create(
                makerspace=makerspace,
                asset_tag=f"{makerspace.slug.upper()}-OSC-{index:02d}",
                defaults={
                    "product": product,
                    "box": box,
                    "serial_number": f"DEMO-{makerspace.slug}-{index:02d}",
                    "status": InventoryAsset.Status.AVAILABLE,
                    "public_self_checkout_enabled": False,
                },
            )
        return 3

    def _machine_service(self, makerspace, requester):
        printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
        machine, _ = Machine.objects.update_or_create(
            makerspace=makerspace,
            name="Demo 3D Printer",
            defaults={
                "machine_type": printer_type,
                "location": "Fabrication Bench",
                "notes": "Seeded kernel machine-service printer.",
                "is_public": True,
                "type_payload": {"model": "Prusa MK4"},
                "created_by": requester,
            },
        )
        MachineConsumablePool.objects.get_or_create(
            makerspace=makerspace,
            machine=machine,
            material="PLA",
            color="Black",
            brand="Demo",
            lot_code="DEMO-PLA",
            defaults={
                "initial_grams": Decimal("1000.00"),
                "remaining_grams": Decimal("1000.00"),
                "low_threshold_grams": Decimal("200.00"),
                "created_by": requester,
            },
        )
        if MachineServiceRequest.objects.filter(
            makerspace=makerspace, title="Demo 3D print request"
        ).exists():
            return 0
        submit_service_request(
            machine,
            requester,
            actor=requester,
            requester_name=requester.username,
            contact_email=requester.email,
            contact_phone="",
            title="Demo 3D print request",
            description="Seeded machine-service sample.",
            capability_payload={
                "requested_material": "PLA",
                "requested_color": "Black",
                "quantity": 1,
                "estimated_grams": "25.00",
            },
        )
        return 1
    def _sync_legacy_hmac_client(self):
        if not settings.HMAC_CLIENT_ID or not settings.HMAC_SECRET:
            return
        client = ApiClient.objects.filter(client_id=settings.HMAC_CLIENT_ID).first()
        if client is None:
            client = ApiClient(client_id=settings.HMAC_CLIENT_ID, label="Legacy frontend")
        client.allowed_origins = list(settings.CORS_ALLOWED_ORIGINS)
        client.set_secret(settings.HMAC_SECRET)
        client.save()
