"""Late source-gate resolution shared by every Django ModelAdmin."""

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME


class AdminSourceGateMixin:
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            self._assert_source_gate(request, object_id=object_id)
        return super().changeform_view(request, object_id, form_url, extra_context)

    def delete_view(self, request, object_id, extra_context=None):
        if request.method == "POST" and self.model._meta.label != "makerspaces.Makerspace":
            self._assert_source_gate(request, object_id=object_id)
        return super().delete_view(request, object_id, extra_context)

    def changelist_view(self, request, extra_context=None):
        if request.method == "POST":
            from apps.tenant_migration.gate_policy import ADMIN_ACTION_EXEMPTIONS

            action_target = (
                f"{self.model._meta.label}.{request.POST.get('action', '')}"
            )
            if action_target not in ADMIN_ACTION_EXEMPTIONS:
                selected = request.POST.getlist(ACTION_CHECKBOX_NAME)
                if selected:
                    self._assert_source_gate(
                        request,
                        queryset=self.model._default_manager.filter(pk__in=selected),
                    )
        return super().changelist_view(request, extra_context)

    def _assert_source_gate(self, request, *, object_id=None, queryset=None):
        from apps.tenant_migration.gate_runtime import assert_write_allowed

        lookup = self.resolve_hidden_lookup()
        if lookup is None:
            return
        if queryset is None and object_id is not None:
            queryset = self.model._default_manager.filter(pk=object_id)
        if queryset is not None:
            makerspace_ids = queryset.values_list(lookup, flat=True).distinct()
            for makerspace_id in sorted(set(makerspace_ids)):
                if makerspace_id is not None:
                    assert_write_allowed(makerspace_id)
            return
        parts = lookup.split("__")
        form_field = parts[0].removesuffix("_id")
        raw = request.POST.get(parts[0]) or request.POST.get(form_field)
        if len(parts) > 1 and raw:
            try:
                field = self.model._meta.get_field(parts[0])
                makerspace_id = (
                    field.related_model._default_manager.filter(pk=raw)
                    .values_list("__".join(parts[1:]), flat=True)
                    .first()
                )
            except (AttributeError, TypeError, ValueError):
                return
            if makerspace_id is not None:
                assert_write_allowed(makerspace_id)
            return
        try:
            makerspace_id = int(raw)
        except (TypeError, ValueError):
            return
        if makerspace_id > 0:
            assert_write_allowed(makerspace_id)
