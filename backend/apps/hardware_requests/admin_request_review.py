"""One request, one decision — the review surface that replaced bulk accept/reject.

Accepting a borrow request RESERVES inventory and rejecting one closes a person's ask, and
neither is a judgement you can make about twenty rows from a checkbox column. The bulk
`accept_selected` / `reject_selected` actions are gone; a decision is made here, on a page
that shows who is asking, whether their contact was ever verified, and exactly what they
want, with a per-item accepted quantity you can lower before you commit stock.

The mutations still go through `request_workflow`, so the state machine, the audit entry
and the notification fan-out are identical to every other surface — only the *entry point*
changed. See the module-level note in `apps.hardware_requests.workflow` for why nothing may
mutate `HardwareRequest.status` directly.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.hardware_requests.admin_workflow import WORKFLOW_EXCEPTIONS
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.request_workflow import accept_request, reject_request


class RequestReviewAdminMixin:
    """Adds `<pk>/review/` to a HardwareRequest ModelAdmin."""

    review_template = "admin/hardware_requests/review.html"

    def get_urls(self):
        from django.urls import path

        return [
            path(
                "<int:request_id>/review/",
                # `admin_view` applies the admin's own authentication and the
                # never-cache headers. Without it this is an ordinary view that any
                # logged-in user could reach, which for a state-changing POST is the
                # whole ballgame.
                self.admin_site.admin_view(self.review_view),
                name="hardware_requests_hardwarerequest_review",
            ),
            *super().get_urls(),
        ]

    def _review_object(self, request, request_id):
        # `self.get_queryset(request)` and NOT `HardwareRequest.objects`: the superadmin
        # queryset excludes hard-hidden makerspaces, and reaching around it here would
        # make this URL the one place that ignores the control-plane hidden-tenant rule.
        queryset = self.get_queryset(request).prefetch_related("items__product")
        obj = queryset.filter(pk=request_id).first()
        if obj is None:
            raise Http404("No hardware request matches the given query.")
        return obj

    def review_view(self, request, request_id):
        obj = self._review_object(request, request_id)
        if not self.has_change_permission(request, obj):
            raise Http404("No hardware request matches the given query.")

        if request.method == "POST":
            return self._apply_review(request, obj)

        return TemplateResponse(
            request,
            self.review_template,
            {
                **self.admin_site.each_context(request),
                "title": f"Review hardware request #{obj.pk}",
                "hardware_request": obj,
                "items": list(obj.items.all()),
                "opts": self.model._meta,
                "is_pending": obj.status == HardwareRequest.Status.PENDING_APPROVAL,
            },
        )

    def _apply_review(self, request, obj):
        changelist = reverse("admin:hardware_requests_hardwarerequest_changelist")
        if "reject" in request.POST:
            reason = request.POST.get("reason", "").strip()
            if not reason:
                self.message_user(request, "Rejection reason is required.", level=messages.ERROR)
                return redirect(request.path)
            try:
                reject_request(request.user, obj, reason)
            except WORKFLOW_EXCEPTIONS as exc:
                self.message_user(request, f"{obj.pk}: {exc}", level=messages.ERROR)
                return redirect(request.path)
            self.message_user(request, f"Rejected hardware request #{obj.pk}.", level=messages.SUCCESS)
            return redirect(changelist)

        try:
            accepted = self._accepted_quantities(request, obj)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return redirect(request.path)

        try:
            accept_request(request.user, obj, accepted=accepted)
        except WORKFLOW_EXCEPTIONS as exc:
            self.message_user(request, f"{obj.pk}: {exc}", level=messages.ERROR)
            return redirect(request.path)
        self.message_user(request, f"Accepted hardware request #{obj.pk}.", level=messages.SUCCESS)
        return redirect(changelist)

    @staticmethod
    def _accepted_quantities(request, obj):
        """Parse the per-item inputs into the map `accept_request` expects.

        Returns `None` when the form carried no quantities at all, which `accept_request`
        reads as "accept everything as requested" — the same default the API uses for an
        omitted `accepted_quantities`. Anything present is parsed as an int here rather
        than handed to the workflow as a string, so a malformed field is an error on this
        page instead of a 500 inside the service.
        """
        quantities = {}
        for item in obj.items.all():
            raw = request.POST.get(f"accepted_quantity_{item.pk}")
            if raw is None or raw == "":
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"Accepted quantity for item {item.pk} must be a whole number.")
            if value < 0 or value > item.requested_quantity:
                raise ValueError(
                    f"Accepted quantity for item {item.pk} must be between 0 and "
                    f"{item.requested_quantity}."
                )
            quantities[item.pk] = value
        return quantities or None
