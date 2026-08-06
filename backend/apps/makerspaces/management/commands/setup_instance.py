import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import apply_profile
from apps.makerspaces.module_profiles import DEFAULT_PROFILE, PROFILES


class Command(BaseCommand):
    help = "Create the first superadmin and makerspace for a self-hosted instance."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=None)
        parser.add_argument("--email", default=os.getenv("SETUP_SUPERADMIN_EMAIL", "admin@example.com"))
        parser.add_argument("--password", default=None)
        parser.add_argument("--makerspace-name", default=os.getenv("SETUP_MAKERSPACE_NAME", "My Makerspace"))
        parser.add_argument("--makerspace-slug", default=os.getenv("SETUP_MAKERSPACE_SLUG", ""))
        parser.add_argument(
            "--profile",
            choices=sorted(PROFILES),
            default=os.getenv("SETUP_MODULE_PROFILE", "") or DEFAULT_PROFILE,
            help="Which modules to install on the first makerspace.",
        )

    def handle(self, *args, **options):
        username = options["username"] or os.getenv("SETUP_SUPERADMIN_USERNAME") or "superadmin"
        env_password = os.getenv("SETUP_SUPERADMIN_PASSWORD")
        explicit_password = bool(options["password"] or env_password)
        password = options["password"] or env_password or "super123"

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": options["email"],
                "role": User.Role.SUPERADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            user.set_password(password)
            user.must_change_password = not explicit_password
            user.save()
        else:
            changed = False
            if not user.is_superuser:
                user.is_superuser = True
                changed = True
            if not user.is_staff:
                user.is_staff = True
                changed = True
            if user.role != User.Role.SUPERADMIN:
                user.role = User.Role.SUPERADMIN
                changed = True
            if changed:
                user.save(update_fields=["is_superuser", "is_staff", "role"])

        slug = options["makerspace_slug"] or slugify(options["makerspace_name"])
        makerspace, space_created = Makerspace.objects.get_or_create(
            slug=slug,
            defaults={"name": options["makerspace_name"], "created_by": user},
        )
        # Only on creation: re-running setup must never silently rewrite the modules an
        # operator has since chosen.
        if space_created:
            apply_profile(makerspace, options["profile"], actor=user)

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Found'} superadmin {user.username}; "
                f"{'created' if space_created else 'found'} makerspace {makerspace.slug}."
            )
        )
        if space_created:
            self.stdout.write(
                f"Installed the '{options['profile']}' module profile "
                f"({len(makerspace.enabled_modules)} modules). "
                "Change it with: python manage.py list_modules / install_module <key>."
            )
        if created and not explicit_password:
            self.stdout.write(
                self.style.WARNING(
                    f"Default superadmin username is {user.username}; "
                    "the default password must be changed on first login."
                )
            )
