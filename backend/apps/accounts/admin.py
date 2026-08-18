from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext
from unfold.admin import ModelAdmin, TabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from rest_framework.exceptions import APIException

from apps.accounts.models import NativeAppRegistration, User
from apps.accounts.transition_services import (
    WalkInTransitionError,
    transition_walk_in_to_account,
)
from apps.admin_api.services_user_access import reset_user_password
from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.models import MakerspaceMembership
from config.admin_access import SuperuserOnlyModelAdmin


class RestrictAccessForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            choice
            for choice in User.AccessStatus.choices
            if choice[0] != User.AccessStatus.ACTIVE
        ],
        required=True,
    )
    reason = forms.CharField(required=True, widget=forms.Textarea)


class MakerspaceMembershipInline(TabularInline):
    model = MakerspaceMembership
    fk_name = "user"
    fields = ("makerspace", "role")
    autocomplete_fields = ("makerspace",)
    extra = 0


@admin.register(User)
class UserAdmin(SuperuserOnlyModelAdmin, DjangoUserAdmin, ModelAdmin):
    actions = ["restrict_access", "restore_access", "reset_password_selected"]
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Space Works Access",
            {
                "fields": (
                    "phone",
                    "external_checkin_user_id",
                    "role",
                    "access_status",
                    "restriction_reason",
                ),
            },
        ),
    )
    list_display = ("username", "email", "role", "access_status", "is_staff")
    list_filter = DjangoUserAdmin.list_filter + (
        "role",
        "access_status",
        "makerspace_memberships__makerspace",
    )
    inlines = (MakerspaceMembershipInline,)

    def user_change_password(self, request, id, form_url=""):
        """Make the inherited password form an explicit account transition."""
        user = self.get_object(request, id)
        if (
            request.method != "POST"
            or user is None
            or not user.is_walk_in
            or not self.has_change_permission(request, user)
        ):
            return super().user_change_password(request, id, form_url)

        form = self.change_password_form(user, request.POST)
        if not form.is_valid() or not form.cleaned_data["set_usable_password"]:
            return super().user_change_password(request, id, form_url)

        password = form.cleaned_data["password1"]

        def write_password(locked_user):
            locked_user.set_password(password)
            locked_user.save(update_fields=["password"])

        try:
            user = transition_walk_in_to_account(
                user,
                actor=request.user,
                credential_writer=write_password,
            )
        except WalkInTransitionError:
            # A concurrent transition won the row lock. The record is now an ordinary
            # account, so the inherited form is again the correct writer.
            return super().user_change_password(request, id, form_url)

        form.user = user
        self.log_change(request, user, self.construct_change_message(request, form, None))
        messages.success(request, gettext("Password changed successfully."))
        update_session_auth_hash(request, user)
        return HttpResponseRedirect(
            reverse(
                f"{self.admin_site.name}:{user._meta.app_label}_{user._meta.model_name}_change",
                args=(user.pk,),
            )
        )

    @admin.action(description="Reset selected user passwords")
    def reset_password_selected(self, request, queryset):
        succeeded, skipped = 0, 0
        for user in queryset:
            try:
                result = reset_user_password(request.user, user.pk)
            except APIException as exc:
                skipped += 1
                self.message_user(
                    request,
                    f"{user.username}: {_api_exception_message(exc)}",
                    level=messages.WARNING,
                )
            else:
                succeeded += 1
                self.message_user(
                    request,
                    f"{result.user.username}: {result.temporary_password}",
                    level=messages.SUCCESS,
                )
        self.message_user(
            request,
            f"Reset {succeeded} password(s); skipped {skipped}.",
            level=messages.SUCCESS if succeeded else messages.WARNING,
        )

    @admin.action(description="Restrict selected users")
    def restrict_access(self, request, queryset):
        if "apply" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Restrict selected users",
                "queryset": queryset,
                "opts": self.model._meta,
                "action_name": "restrict_access",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
                "status_choices": RestrictAccessForm.base_fields["status"].choices,
            }
            return TemplateResponse(
                request,
                "admin/accounts/restrict_access_action.html",
                context,
            )

        form = RestrictAccessForm(request.POST)
        if not form.is_valid():
            self.message_user(request, form.errors, level=messages.ERROR)
            return None

        success_count = 0
        status = form.cleaned_data["status"]
        reason = form.cleaned_data["reason"]
        for user in queryset:
            user.access_status = status
            user.restriction_reason = reason
            user.save(update_fields=["access_status", "restriction_reason"])
            audit.record(
                request.user,
                "user.access_restricted",
                target=user,
                meta={"status": user.access_status, "reason": user.restriction_reason},
            )
            success_count += 1

        self.message_user(
            request,
            f"Restricted {success_count} user(s).",
            level=messages.SUCCESS,
        )
        return None

    @admin.action(description="Restore selected users")
    def restore_access(self, request, queryset):
        success_count = 0
        for user in queryset:
            try:
                with transaction.atomic():
                    locked = User.objects.select_for_update().get(pk=user.pk)
                    if locked.access_status != User.AccessStatus.ACTIVE and locked.is_active:
                        memberships = MakerspaceMembership.objects.select_related(
                            "makerspace"
                        ).filter(user=locked).order_by("makerspace_id")
                        for membership in memberships:
                            limits.check_quota(
                                membership.makerspace, "staff", adding=1
                            )
                    locked.access_status = User.AccessStatus.ACTIVE
                    locked.restriction_reason = ""
                    locked.save(update_fields=["access_status", "restriction_reason"])
                    audit.record(request.user, "user.access_restored", target=locked)
            except APIException as exc:
                self.message_user(
                    request,
                    f"{user.username}: {_api_exception_message(exc)}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"Restored access for {success_count} user(s).",
                level=messages.SUCCESS,
            )


@admin.register(NativeAppRegistration)
class NativeAppRegistrationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "app_id", "platform", "environment", "makerspace", "status", "updated_at",
    )
    list_filter = ("status", "platform", "environment", "makerspace")
    search_fields = ("app_id", "verifier_config_key", "makerspace__name")
    autocomplete_fields = ("makerspace", "approved_by")
    readonly_fields = ("created_at", "updated_at")


admin.site.unregister(Group)

from apps.accounts import admin_claim, admin_social  # noqa: E402,F401
from apps.accounts import admin_password_reset  # noqa: E402,F401


@admin.register(Group)
class GroupAdmin(SuperuserOnlyModelAdmin, DjangoGroupAdmin, ModelAdmin):
    pass


def _api_exception_message(exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return "; ".join(f"{key}: {value}" for key, value in detail.items())
    return str(detail or exc)
