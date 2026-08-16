from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.makerspaces.hosting import invalidate
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


class Command(BaseCommand):
    help = "Promote self-host custom domains to VERIFIED (no-op on a managed instance)."

    def handle(self, *args, **options):
        if str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip():
            self.stdout.write("Managed instance (PLATFORM_DOMAIN_SUFFIX set) — nothing to reconcile.")
            return
        updated = (
            servable_queryset(Makerspace.objects.filter(frontend_domain__isnull=False))
            .exclude(frontend_domain="")
            .exclude(frontend_domain_status=Makerspace.DomainStatus.VERIFIED)
            .update(
                frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
                domain_verified_at=timezone.now(),
            )
        )
        invalidate()
        self.stdout.write(self.style.SUCCESS(f"Reconciled {updated} self-host custom domain(s)."))
