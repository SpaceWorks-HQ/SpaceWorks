from django.contrib import admin

from unfold.admin import ModelAdmin

from apps.machines import services
from apps.machines.models import (
    Machine,
    MachineConsumable,
    MachineDocument,
    MachineErrorLog,
    MachineOperator,
    MachineType,
    MachineUsageEntry,
    PrintingCutoverRepair,
    RoleMachineScope,
    RoleMachineTypeScope,
    PrintingCutoverState,
    MachineConsumablePool,
    MachineConsumableAdjustment,
    MachineServiceRequest,
    ServiceBucket,
    ServiceQueue,
    ServiceRequestConsumption,
    ServiceRequestFile,
)
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(MachineType)
class MachineTypeAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "slug", "name", "makerspace", "is_builtin", "managing_action")
    list_filter = ("is_builtin", "makerspace")
    search_fields = ("slug", "name", "makerspace__name")
    raw_id_fields = ("makerspace",)
    readonly_fields = ("is_builtin", "managing_action")

    # Built-in global types are load-bearing (printer auto-link resolves 3d_printer)
    # and are only restored by the seed migration — never let the admin delete them.
    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_builtin:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Machine)
class MachineAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        'id', 'name', 'makerspace', 'machine_type', 'status', 'is_public', 'is_active'
    )
    list_filter = ('status', 'is_public', 'is_active', 'makerspace', 'machine_type')
    search_fields = ("name", "location", "makerspace__name")
    raw_id_fields = ("makerspace", "machine_type", "created_by")
    # status/is_active/link are service-owned — never raw-edited in the admin.
    readonly_fields = (
        "status",
        'is_public',
        "is_active",
        "image_key",
        "created_by",
        "created_at",
        "updated_at",
    )
    actions = ["retire_selected", "unretire_selected", "mark_maintenance", "mark_idle"]

    # No hard delete of machines anywhere — retirement is the only lifecycle action.
    def has_delete_permission(self, request, obj=None):
        return False

    def _run(self, request, queryset, fn, label):
        done, failed = 0, 0
        for machine in queryset:
            try:
                fn(machine, request.user)
                done += 1
            except Exception as exc:  # surface, never 500 the changelist
                failed += 1
                self.message_user(request, f"{machine}: {exc}", level="ERROR")
        if done:
            self.message_user(request, f"{label} {done} machine(s).")

    @admin.action(description="Retire selected machines")
    def retire_selected(self, request, queryset):
        self._run(request, queryset, services.retire_machine, "Retired")

    @admin.action(description="Reactivate selected machines")
    def unretire_selected(self, request, queryset):
        self._run(request, queryset, services.unretire_machine, "Reactivated")

    @admin.action(description="Set status: maintenance")
    def mark_maintenance(self, request, queryset):
        self._run(
            request, queryset,
            lambda m, u: services.set_status(m, u, Machine.Status.MAINTENANCE),
            "Set maintenance on",
        )

    @admin.action(description="Set status: idle")
    def mark_idle(self, request, queryset):
        self._run(
            request, queryset,
            lambda m, u: services.set_status(m, u, Machine.Status.IDLE),
            "Set idle on",
        )


class _ReadOnlyMachineChildAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MachineOperator)
class MachineOperatorAdmin(_ReadOnlyMachineChildAdmin):
    # Read-only in /control/: operator rows are only ever written through the
    # assignment service (active-membership validation, delegation rules, audit).
    list_display = ("id", "machine", "user", "access_level", "assigned_by", "assigned_at")
    list_filter = ("access_level",)
    search_fields = ("machine__name", "user__username")


@admin.register(MachineUsageEntry)
class MachineUsageEntryAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "machine", "hours", "source", "logged_by", "created_at")
    list_filter = ("source",)
    search_fields = ("machine__name",)


@admin.register(PrintingCutoverState)
class PrintingCutoverStateAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("makerspace", "reconciled_at", "kernel_authoritative_at")
    list_filter = ("makerspace",)


@admin.register(PrintingCutoverRepair)
class PrintingCutoverRepairAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "makerspace", "kind", "legacy_model", "legacy_id", "created_at", "resolved_at")
    list_filter = ("kind", "makerspace")
    search_fields = ("legacy_model", "legacy_id")


@admin.register(MachineDocument)
class MachineDocumentAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "machine", "doc_type", "original_filename", "content_type", "created_at")
    list_filter = ("doc_type", "content_type")
    search_fields = ("machine__name", "original_filename", "object_key")


@admin.register(MachineErrorLog)
class MachineErrorLogAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "machine", "severity", "logged_by", "created_at")
    list_filter = ("severity",)
    search_fields = ("machine__name", "message")


@admin.register(MachineConsumable)
class MachineConsumableAdmin(_ReadOnlyMachineChildAdmin):
    list_display = (
        "id", "machine", "measurement", "product", "label", "remaining", "created_at"
    )
    list_filter = ("measurement",)
    search_fields = ("machine__name", "product__name", "label")


@admin.register(ServiceBucket)
class ServiceBucketAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "machine", "name", "is_active", "created_at")
    list_filter = ("is_active", "machine")
    search_fields = ("machine__name", "name")


@admin.register(ServiceQueue)
class ServiceQueueAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "name", "makerspace", "machine_type", "is_active", "allocation_policy")
    list_filter = ("is_active", "allocation_policy", "machine_type")
    search_fields = ("name", "makerspace__name")


@admin.register(MachineConsumablePool)
class MachineConsumablePoolAdmin(_ReadOnlyMachineChildAdmin):
    list_display = (
        "id", "label", "makerspace", "machine", "machine_type", "remaining_grams",
        "is_active", "is_public",
    )
    list_filter = ("is_active", "is_public", "material", "machine_type")
    search_fields = (
        "material", "color", "brand", "machine__name", "machine_type__name",
        "machine_type__slug",
    )


@admin.register(MachineConsumableAdjustment)
class MachineConsumableAdjustmentAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "consumable_pool", "kind", "quantity_delta", "service_request", "created_at")
    list_filter = ("kind",)
    search_fields = ("consumable_pool__material", "service_request__title")


@admin.register(MachineServiceRequest)
class MachineServiceRequestAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "title", "bucket", "assigned_machine", "status", "created_at")
    list_filter = ("status", "assigned_machine", "bucket__machine")
    search_fields = ("title", "requester_name", "contact_email")
    raw_id_fields = ("bucket", "requester", "assigned_machine")


@admin.register(ServiceRequestFile)
class ServiceRequestFileAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "service_request", "machine", "kind", "original_filename", "size_bytes", "attached_at")
    list_filter = ("kind", "machine")
    search_fields = ("original_filename", "service_request__title", "machine__name")
    raw_id_fields = ("service_request", "machine")


@admin.register(ServiceRequestConsumption)
class ServiceRequestConsumptionAdmin(_ReadOnlyMachineChildAdmin):
    list_display = ("id", "service_request", "machine_consumable", "measurement", "quantity", "outcome", "created_at")
    list_filter = ("outcome", "measurement", "machine_consumable__machine")
    search_fields = ("service_request__title", "machine_consumable__label", "machine_consumable__machine__name")
    raw_id_fields = ("service_request", "machine_consumable", "product", "created_by")


@admin.register(RoleMachineTypeScope)
class RoleMachineTypeScopeAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Which machine types a role's MANAGE_MACHINES grant reaches.

    Writable here on purpose: this is the break-glass surface for a deployment that has
    scoped a role down to nothing by accident, and the alternative is a shell. Staff edit
    these through the role editor, which enforces the tenant match; the admin is
    superadmin-only and `role_scope` re-checks the makerspace at resolution anyway, so a
    bad row written here is inert rather than a cross-tenant leak.
    """

    list_display = ("id", "role", "machine_type", "created_at")
    list_filter = ("role__makerspace",)
    search_fields = ("role__name", "machine_type__name")
    raw_id_fields = ("role", "machine_type")
    readonly_fields = ("created_at",)


@admin.register(RoleMachineScope)
class RoleMachineScopeAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Which individual machines a role's MANAGE_MACHINES grant reaches."""

    list_display = ("id", "role", "machine", "created_at")
    list_filter = ("role__makerspace",)
    search_fields = ("role__name", "machine__name")
    raw_id_fields = ("role", "machine")
    readonly_fields = ("created_at",)
