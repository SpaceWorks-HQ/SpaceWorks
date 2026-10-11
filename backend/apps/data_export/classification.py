"""Literal model classification: what a tenant export includes, references and omits.

The field names are deliberately literal.  Building this from ``_meta`` would make a new
database column export itself before a security review could classify it.
"""

from .types import Exported, GlobalReference, NotTenantData, OmittedModel
from .classification_7c import LABEL_EXPORTED_MODEL_FIELDS
from .classification_7b import PRINTER_EXPORTED_MODEL_FIELDS
from .classification_devices import DEVICE_EXPORTED_MODEL_FIELDS, DEVICE_OMITTED_MODELS
from .classification_domain import EXPORTED_MODEL_FIELDS as _DOMAIN_EXPORTED_MODEL_FIELDS
from .classification_platform import GLOBAL_MODELS
from .classification_platform import OMITTED_MODELS as _PLATFORM_OMITTED_MODELS

EXPORTED_MODEL_FIELDS = {**_DOMAIN_EXPORTED_MODEL_FIELDS, **DEVICE_EXPORTED_MODEL_FIELDS, **PRINTER_EXPORTED_MODEL_FIELDS, **LABEL_EXPORTED_MODEL_FIELDS}
from .classification_wp4 import exported_fields, OMITTED_MODELS as WP4_OMITTED
EXPORTED_MODEL_FIELDS = exported_fields(EXPORTED_MODEL_FIELDS)
OMITTED_MODELS = {**_PLATFORM_OMITTED_MODELS, **DEVICE_OMITTED_MODELS, **WP4_OMITTED}
EXPORTED_MODELS = frozenset(EXPORTED_MODEL_FIELDS)

NOT_TENANT_MODELS = {
    label: NotTenantData(reason) for label, reason in OMITTED_MODELS.items()
}
MODELS = {
    **{label: Exported() for label in EXPORTED_MODELS},
    **GLOBAL_MODELS,
    **{label: OmittedModel(value.reason) for label, value in NOT_TENANT_MODELS.items()},
}
