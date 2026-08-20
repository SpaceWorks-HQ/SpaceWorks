"""AuditLog target reference declarations used by portable tenant archives."""

from dataclasses import dataclass
from enum import StrEnum

from apps.data_export.models import MODELS
from apps.data_export.types import Exported, GlobalReference, OmittedModel


SOURCE_ID_PREFIX = "source:"


class AuditReferenceDisposition(StrEnum):
    REMAP = "remap"
    NULL = "null"
    SOURCE_LOCAL_SNAPSHOT = "source_local_snapshot"


@dataclass(frozen=True)
class AuditReference:
    disposition: AuditReferenceDisposition
    target_model_label: str | None
    kind: str = ""


def normalize_audit_target_type(model_label: str) -> str:
    """Return the exact lowercase label written by ``audit.services.record``."""
    app_label, separator, model_name = str(model_label).partition(".")
    if not separator or not app_label or not model_name:
        return str(model_label).lower()
    return f"{app_label.lower()}.{model_name.lower()}"


def audit_target_dispositions(models=MODELS):
    """Derive recognised audit targets from the total export model registry."""
    dispositions = {}
    for label, model_disposition in models.items():
        key = normalize_audit_target_type(label)
        if isinstance(model_disposition, Exported):
            dispositions[key] = AuditReference(
                AuditReferenceDisposition.REMAP, label
            )
        elif isinstance(model_disposition, GlobalReference):
            dispositions[key] = AuditReference(
                AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
                label,
                "audit_user_target" if label == "accounts.User" else "audit_global_target",
            )
        elif isinstance(model_disposition, OmittedModel):
            dispositions[key] = AuditReference(
                AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
                label,
                "audit_omitted_target_model",
            )
    return dispositions


AUDIT_TARGET_DISPOSITIONS = audit_target_dispositions()
UNRECOGNISED_AUDIT_TARGET = AuditReference(
    AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
    None,
    "audit_unrecognised_or_dropped_target",
)
