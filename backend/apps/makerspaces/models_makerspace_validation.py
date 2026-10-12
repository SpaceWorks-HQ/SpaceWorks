"""Model validation for makerspace control forms."""

from django.core.exceptions import ValidationError

from apps.makerspaces.capabilities import prune_features, validate_capabilities
from apps.makerspaces.validators import validate_presence_presets
from apps.makerspaces.theme_validation import validate_theme_config


def clean_makerspace(self):
    try:
        validate_theme_config(self.theme_config)
    except ValidationError as exc:
        raise ValidationError({"theme_config": exc.messages}) from exc
    if self.presence_preset_minutes:
        validate_presence_presets(self.presence_preset_minutes)
    # Drop features whose module is not in this row's set BEFORE validating. The
    # module set is authoritative — `_canonical_modules` already normalizes rather
    # than rejects (it adds core keys back), and this is the same class of
    # normalization on the other axis.
    #
    # Without it a row can be born invalid and then never saved again: creating a
    # makerspace with a narrow `enabled_modules` still takes the FIELD default for
    # `enabled_features`, which includes the default-on `payments.enabled` and
    # `mobile.push`. Those demand modules the row does not have, so `clean()` raised
    # on every subsequent save — including saves that touched neither field, such as
    # a Space Manager toggling public stats.
    #
    # The user-facing strictness is unaffected: the `/control/` capability matrix and
    # `module_install` call `validate_capabilities` directly before saving, so a
    # conflict the operator actually expressed is still reported there rather than
    # silently cleared.
    kept, _dropped = prune_features(
        self.enabled_features or [], self.enabled_modules or []
    )
    self.enabled_modules, self.enabled_features = validate_capabilities(
        self.enabled_modules or [], kept
    )
    if self.hidden_from_central_directory and not self.frontend_domain:
        raise ValidationError(
            {
                "hidden_from_central_directory": (
                    "A frontend domain is required to hide a makerspace from the central directory."
                )
            }
        )
    if self.geofence_enabled and not self.geofence_effective:
        raise ValidationError({"geofence_enabled": "Set both latitude and longitude before enabling the geofence."})
