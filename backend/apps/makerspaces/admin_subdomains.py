from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from unfold.admin import ModelAdmin

from apps.audit import services as audit
from apps.makerspaces.models import Makerspace, SubdomainRequest
from apps.makerspaces.provisioning import provision_subdomain
from apps.makerspaces.subdomain_notifications import notify_subdomain_request_resolved
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(SubdomainRequest)
class SubdomainRequestAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["approve_and_provision", "reject_selected"]
    list_display = (
        "requested_label",
        "makerspace",
        "requested_by",
        "status",
        "created_at",
    )
    list_filter = ("status", "makerspace")
    search_fields = ("requested_label",)
    readonly_fields = (
        "status",
        "requested_label",
        "makerspace",
        "requested_by",
        "decided_by",
        "decided_at",
        "created_at",
        "updated_at",
    )

    @admin.action(description="Approve selected subdomain requests and provision")
    def approve_and_provision(self, request, queryset):
        approved = 0
        skipped = 0
        for req in queryset.select_related("makerspace", "requested_by"):
            if req.status != SubdomainRequest.Status.PENDING:
                skipped += 1
                continue

            try:
                with transaction.atomic():
                    locked_req = SubdomainRequest.objects.select_for_update().get(pk=req.pk)
                    if locked_req.status != SubdomainRequest.Status.PENDING:
                        skipped += 1
                        continue

                    locked_ms = Makerspace.objects.select_for_update().get(
                        pk=locked_req.makerspace_id
                    )
                    suffix = str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip().lower()
                    current = (locked_ms.frontend_domain or "").lower()
                    if suffix and current and current.endswith(suffix):
                        raise DjangoValidationError(
                            "This makerspace already has a platform subdomain."
                        )

                    locked_ms = provision_subdomain(
                        locked_ms,
                        locked_req.requested_label,
                        request.user,
                    )
                    locked_req.status = SubdomainRequest.Status.APPROVED
                    locked_req.decided_by = request.user
                    locked_req.decided_at = timezone.now()
                    locked_req.save(
                        update_fields=[
                            "status",
                            "decided_by",
                            "decided_at",
                            "updated_at",
                        ]
                    )
            except DjangoValidationError as exc:
                self.message_user(
                    request,
                    f"{req.pk}: {getattr(exc, 'message', exc)}",
                    level=messages.ERROR,
                )
                continue

            audit.record(
                request.user,
                "makerspace.subdomain_request_approved",
                makerspace=locked_ms,
                target=locked_req,
                meta={"frontend_domain": locked_ms.frontend_domain},
            )
            try:
                notify_subdomain_request_resolved(locked_req)
            except Exception:
                pass
            approved += 1

        self.message_user(request, f"Approved {approved}, skipped {skipped}.")

    @admin.action(description="Reject selected subdomain requests")
    def reject_selected(self, request, queryset):
        rejected = 0
        for req in queryset.select_related("makerspace", "requested_by"):
            if req.status != SubdomainRequest.Status.PENDING:
                continue

            with transaction.atomic():
                locked_req = SubdomainRequest.objects.select_for_update().get(pk=req.pk)
                if locked_req.status != SubdomainRequest.Status.PENDING:
                    continue
                locked_req.status = SubdomainRequest.Status.REJECTED
                locked_req.decided_by = request.user
                locked_req.decided_at = timezone.now()
                locked_req.save(
                    update_fields=[
                        "status",
                        "decided_by",
                        "decided_at",
                        "updated_at",
                    ]
                )

            audit.record(
                request.user,
                "makerspace.subdomain_request_rejected",
                makerspace=locked_req.makerspace,
                target=locked_req,
            )
            try:
                notify_subdomain_request_resolved(locked_req)
            except Exception:
                pass
            rejected += 1

        self.message_user(request, f"Rejected {rejected}.")
