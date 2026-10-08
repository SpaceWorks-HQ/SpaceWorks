"""The /control/ lifecycle actions on a makerspace: archive, unarchive, purge.

Split out of `admin.py` (which sat at the 300-line ceiling) unchanged. Every action
routes through `apps.makerspaces.lifecycle` -- the single lifecycle source -- and never
writes `archived_at` itself.
"""

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse

from apps.makerspaces.models import MakerspaceArchiveRequest


class MakerspaceLifecycleActionsMixin:
    @admin.action(description="Archive selected makerspaces")
    def archive_makerspaces(self, request, queryset):
        from apps.makerspaces import lifecycle

        makerspaces = list(queryset)
        if "confirm_archive" not in request.POST:
            pending_by_makerspace = {
                archive_request.makerspace_id: archive_request
                for archive_request in MakerspaceArchiveRequest.objects.filter(
                    makerspace__in=makerspaces,
                    status=MakerspaceArchiveRequest.Status.PENDING,
                ).select_related("requested_by")
            }
            context = {
                **self.admin_site.each_context(request),
                "title": "Archive selected makerspaces",
                "makerspaces": [
                    {
                        "object": makerspace,
                        "pending_archive_request": pending_by_makerspace.get(makerspace.pk),
                        **lifecycle.archive_impact(makerspace),
                    }
                    for makerspace in makerspaces
                ],
                "opts": self.model._meta,
                "action_name": "archive_makerspaces",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/makerspaces/archive_confirmation.html",
                context,
            )

        for makerspace in makerspaces:
            try:
                lifecycle.archive(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Archived makerspace {makerspace.name} ({makerspace.slug}).",
                    level=messages.SUCCESS,
                )

    @admin.action(description="Unarchive selected makerspaces")
    def unarchive_makerspaces(self, request, queryset):
        from apps.makerspaces import lifecycle

        for makerspace in list(queryset):
            try:
                lifecycle.unarchive(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Unarchived makerspace {makerspace.name} ({makerspace.slug}).",
                    level=messages.SUCCESS,
                )

    @admin.action(description="Purge selected archived makerspaces")
    def purge_makerspaces(self, request, queryset):
        makerspaces = list(queryset)
        if "confirm_purge" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Purge selected makerspaces",
                "queryset": makerspaces,
                "opts": self.model._meta,
                "action_name": "purge_makerspaces",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/makerspaces/purge_confirmation.html",
                context,
            )

        from apps.makerspaces import lifecycle

        for makerspace in makerspaces:
            if request.POST.get(f"slug_{makerspace.pk}", "") != makerspace.slug:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): slug confirmation did not match",
                    level=messages.ERROR,
                )
                continue

            name = makerspace.name
            slug = makerspace.slug
            try:
                lifecycle.purge(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{name} ({slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Purged makerspace {name} ({slug}).",
                    level=messages.SUCCESS,
                )
        return None
