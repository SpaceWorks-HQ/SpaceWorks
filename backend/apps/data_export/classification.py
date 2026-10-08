"""Literal model classification: what a tenant export includes, references and omits.

The field names are deliberately literal.  Building this from ``_meta`` would make a new
database column export itself before a security review could classify it.
"""

from .types import Exported, GlobalReference, NotTenantData, OmittedModel
from .classification_domain import EXPORTED_MODEL_FIELDS
from .classification_platform import GLOBAL_MODELS, OMITTED_MODELS
from .types import Exported, NotTenantData, OmittedModel

EXPORTED_MODELS = frozenset(EXPORTED_MODEL_FIELDS)

NOT_TENANT_MODELS = {
    label: NotTenantData(reason) for label, reason in OMITTED_MODELS.items()
}
MODELS = {
    **{label: Exported() for label in EXPORTED_MODELS},
    **GLOBAL_MODELS,
    **{label: OmittedModel(value.reason) for label, value in NOT_TENANT_MODELS.items()},
}
