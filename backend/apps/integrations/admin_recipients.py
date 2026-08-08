from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
    RecipientCategoryScope,
    RecipientMachineScope,
    RecipientMachineTypeScope,
)
from config.admin_access import SuperuserOnlyModelAdmin


class NotificationRecipientAdminForm(forms.ModelForm):
    class Meta:
        model = NotificationRecipient
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        makerspace = cleaned.get("makerspace")
        kind = cleaned.get("kind")
        role = cleaned.get("role")
        user = cleaned.get("user")

        # The DB check constraint already rejects a kind/target mismatch, but a
        # constraint violation surfaces as a 500 rather than a field error, so mirror it.
        if kind == NotificationRecipientKind.ROLE and role is None:
            raise forms.ValidationError({"role": "A role recipient needs a role."})
        if kind == NotificationRecipientKind.USER and user is None:
            raise forms.ValidationError({"user": "A named recipient needs a user."})
        if kind in (NotificationRecipientKind.REQUESTER, NotificationRecipientKind.MEMBERS):
            if role is not None or user is not None:
                raise forms.ValidationError(
                    "Requester and all-member rows carry no role or user."
                )

        if makerspace is None:
            return cleaned

        # Tenancy is re-checked at send time (resolution always ANDs the makerspace), so a
        # bad row here is inert rather than a leak. Refusing it at the form still matters:
        # a silently inert rule reads to an operator as a rule that is working.
        if role is not None and role.makerspace_id != makerspace.pk:
            raise forms.ValidationError(
                {"role": "Role must belong to the same makerspace."}
            )
        # D4: a named user must hold a membership of this makerspace. Notification bodies
        # carry requester names, machine detail and booking info; addressing them to an
        # arbitrary platform account is a hand-operated data leak. An external contractor
        # gets a no-action Member role first.
        if user is not None:
            from apps.makerspaces.models import MakerspaceMembership

            has_membership = MakerspaceMembership.objects.filter(
                makerspace=makerspace, user=user, status="active"
            ).exists()
            if not has_membership:
                raise forms.ValidationError(
                    {"user": "User must hold an active membership of this makerspace."}
                )
        return cleaned


class RecipientMachineTypeScopeInline(TabularInline):
    model = RecipientMachineTypeScope
    extra = 0


class RecipientMachineScopeInline(TabularInline):
    model = RecipientMachineScope
    extra = 0


class RecipientCategoryScopeInline(TabularInline):
    model = RecipientCategoryScope
    extra = 0


@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Per-event recipient selection. The staff console is the primary write surface;
    this exists so a superadmin can inspect and repair rows.

    Scope inlines are optional narrowing: no links means the rule matches every subject.
    """

    form = NotificationRecipientAdminForm
    inlines = [
        RecipientMachineTypeScopeInline,
        RecipientMachineScopeInline,
        RecipientCategoryScopeInline,
    ]
    list_display = ("makerspace", "feature", "event", "kind", "role", "user", "created_at")
    list_filter = ("makerspace", "feature", "kind")
    search_fields = ("event", "user__username", "user__email", "role__name")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
