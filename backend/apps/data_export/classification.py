"""Literal model classification: what a tenant export includes, references and omits.

The field names are deliberately literal.  Building this from ``_meta`` would make a new
database column export itself before a security review could classify it.
"""

from .types import Exported, NotTenantData, OmittedModel
from .classification_7c import LABEL_EXPORTED_MODEL_FIELDS
from .classification_7b import PRINTER_EXPORTED_MODEL_FIELDS
from .classification_devices import DEVICE_EXPORTED_MODEL_FIELDS, DEVICE_OMITTED_MODELS
from .classification_domain import EXPORTED_MODEL_FIELDS as _DOMAIN_EXPORTED_MODEL_FIELDS
from .classification_platform import GLOBAL_MODELS
from .classification_platform import OMITTED_MODELS as _PLATFORM_OMITTED_MODELS
from .classification_modules import EXPORTED_MODEL_FIELDS as _MODULE_FIELDS
from .classification_w7_events import extend_event_export_fields
from .classification_wp3 import WP3_EXPORTED_FIELDS, WP3_OMITTED_MODELS
from .classification_wp4 import exported_fields, OMITTED_MODELS as WP4_OMITTED

EXPORTED_MODEL_FIELDS = {
    **_DOMAIN_EXPORTED_MODEL_FIELDS,
    **DEVICE_EXPORTED_MODEL_FIELDS,
    **PRINTER_EXPORTED_MODEL_FIELDS,
    **LABEL_EXPORTED_MODEL_FIELDS,
    **_MODULE_FIELDS,
    **WP3_EXPORTED_FIELDS,
}
extend_event_export_fields(EXPORTED_MODEL_FIELDS)
EXPORTED_MODEL_FIELDS["bookings.Booking"] += " calendar_sequence calendar_updated_at"
EXPORTED_MODEL_FIELDS["notifications.MemberNotificationPreference"] += " daily_digest"
EXPORTED_MODEL_FIELDS = exported_fields(EXPORTED_MODEL_FIELDS)
OMITTED_MODELS = {
    **_PLATFORM_OMITTED_MODELS, **DEVICE_OMITTED_MODELS,
    **WP3_OMITTED_MODELS, **WP4_OMITTED,
}
EXPORTED_MODELS = frozenset(EXPORTED_MODEL_FIELDS)

NOT_TENANT_MODELS = {
    label: NotTenantData(reason) for label, reason in OMITTED_MODELS.items()
}
MODELS = {
    **{label: Exported() for label in EXPORTED_MODELS},
    **GLOBAL_MODELS,
    **{label: OmittedModel(value.reason) for label, value in NOT_TENANT_MODELS.items()},
}
