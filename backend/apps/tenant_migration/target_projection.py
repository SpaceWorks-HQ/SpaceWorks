"""Explicit public barrel for target-owned portable-archive projection policies.

Source archive data is never authority to configure trust on the target.
Domain declarations live in small sibling modules; imports remain compatible.
"""

from .target_projection_types import (
    ForeignKeyPolicy,
    ReferenceDisposition,
    RowDisposition,
    RowPolicy,
    SeededResolution,
    TargetField,
)
from .target_projection_fields import TARGET_FIELD_PROJECTION, _default
from .target_projection_rows import ROW_POLICIES
from .target_projection_references import (
    DROPPED_NOTIFICATION_RECIPIENT_KINDS,
    FK_POLICIES,
    SEEDED_RESOLUTIONS,
)
