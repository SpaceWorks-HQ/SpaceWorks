"""Superadmin-only structured capability controls for Makerspace admin."""

from django import forms

from apps.audit import services as audit
from apps.makerspaces.capabilities import FEATURE_DEFINITIONS, validate_capabilities
from apps.makerspaces.admin_images import MakerspaceAdminForm as ImageMakerspaceAdminForm
from apps.makerspaces.module_registry import MODULES
from apps.makerspaces.request_access import effective_policy


class CapabilityMatrixWidget(forms.CheckboxSelectMultiple):
    template_name = "admin/makerspaces/capability_matrix.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # Authoritative parent map (feature option value -> parent module or None) so the
        # client derives the disable rule from the real definition instead of guessing from
        # the key. Parentless features (parent is None) must never be disabled: a disabled
        # checkbox is omitted from POST, which would silently clear the capability on save.
        context["feature_parents"] = {
            f"feature:{item.key}": item.parent_module for item in FEATURE_DEFINITIONS
        }
        return context


def _module_label(definition):
    # Core is labelled, not disabled: a disabled checkbox is omitted from POST, and
    # unchecking core is already harmless because canonicalization adds it back.
    suffix = " (core, always on)" if definition.is_core else ""
    if definition.requires_modules:
        suffix += f" (requires {', '.join(definition.requires_modules)})"
    return f"{definition.label}{suffix}"


def _feature_label(feature):
    requirements = [
        requirement
        for requirement in (feature.parent_module, *feature.requires_modules, *feature.requires_features)
        if requirement
    ]
    if not requirements:
        return f"-> {feature.label}"
    return f"-> {feature.label} (requires {', '.join(requirements)})"

class MakerspaceAdminForm(ImageMakerspaceAdminForm):
    capabilities = forms.MultipleChoiceField(
        required=False,
        label="Modules and features",
        widget=CapabilityMatrixWidget,
    )

    class Meta(ImageMakerspaceAdminForm.Meta):
        exclude = ("enabled_modules", "enabled_features")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sourced from the registry, not "defaults + keys already on the row". That old
        # rule meant a module absent from the defaults could never be offered on a new
        # makerspace -- which is why `notifications` was enforced but unreachable.
        choices = [
            (f"module:{definition.key}", _module_label(definition))
            for definition in MODULES
        ]
        # Unknown legacy keys stay selectable so saving cannot silently drop them.
        known = {definition.key for definition in MODULES}
        choices.extend(
            (f"module:{key}", f"{key.replace('_', ' ').title()} (unrecognised)")
            for key in (self.instance.enabled_modules or [])
            if key not in known
        )
        choices.extend(
            (f"feature:{item.key}", _feature_label(item))
            for item in FEATURE_DEFINITIONS
        )
        self.fields["capabilities"].choices = choices
        selected = [f"module:{key}" for key in self.instance.enabled_modules or []]
        selected.extend(f"feature:{key}" for key in self.instance.enabled_features or [])
        self.initial["capabilities"] = selected
        self.capability_before = {
            "modules": sorted(set(self.instance.enabled_modules or [])),
            "features": sorted(set(self.instance.enabled_features or [])),
        }
        # Captured here, from the UNMODIFIED instance: `clean_capabilities` rewrites
        # `enabled_modules` in place, so by `save_model` the old policy is gone. Ticking
        # `membership` in this matrix forces account-less requests off inside
        # `Makerspace.save()`, and the module/feature lists alone cannot tell an
        # `anyone -> members` change from an `accounts -> members` one.
        self.request_access_before = effective_policy(self.instance)

    def clean_capabilities(self):
        values = self.cleaned_data["capabilities"]
        modules = [value.removeprefix("module:") for value in values if value.startswith("module:")]
        features = [value.removeprefix("feature:") for value in values if value.startswith("feature:")]
        try:
            modules, features = validate_capabilities(modules, features)
        except Exception as exc:
            raise forms.ValidationError(exc.messages) from exc
        self.instance.enabled_modules = modules
        self.instance.enabled_features = features
        return values


class MakerspaceCapabilityAdminMixin:
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        before = getattr(form, "capability_before", {"modules": [], "features": []})
        after = {
            "modules": sorted(set(obj.enabled_modules or [])),
            "features": sorted(set(obj.enabled_features or [])),
        }
        request_access_before = getattr(form, "request_access_before", None)
        request_access_after = effective_policy(obj)
        request_access_changed = (
            request_access_before is not None
            and request_access_before != request_access_after
        )
        if change and (before != after or request_access_changed):
            meta = {"before": before, "after": after}
            if request_access_changed:
                meta["request_access"] = {
                    "before": request_access_before,
                    "after": request_access_after,
                }
            audit.record(
                request.user,
                "makerspace.capabilities_changed",
                makerspace=obj,
                target=obj,
                meta=meta,
            )
