# Service-request models are kept separate so the long-lived machine catalog stays
# compact; importing here preserves the app's established public model surface.
from .models_service import (
    MachineConsumableAdjustment,
    MachineConsumablePool,
    MachineServiceRequest,
    ServiceBucket,
    ServiceQueue,
    ServiceRequestConsumption,
    ServiceRequestFile,
    get_or_create_default_bucket,
)
from .printing_cutover_models import PrintingCutoverRepair, PrintingCutoverState

# Role -> machine/type scope links. Imported here so Django registers them with this app;
# they use string FK references, so the import order relative to MachineType/Machine below
# does not matter.
from .models_role_scope import RoleMachineScope, RoleMachineTypeScope
from .models_catalog import (
    Machine,
    MachineOperator,
    MachineType,
    MakerspaceMachineTypePricing,
)
from .models_usage import (
    MachineConsumable,
    MachineDocument,
    MachineErrorLog,
    MachineUsageEntry,
    MachineUsageEntryQuerySet,
)

__all__ = [
    "Machine",
    "MachineConsumable",
    "MachineConsumableAdjustment",
    "MachineConsumablePool",
    "MachineDocument",
    "MachineErrorLog",
    "MachineOperator",
    "MachineServiceRequest",
    "MachineType",
    "MachineUsageEntry",
    "MachineUsageEntryQuerySet",
    "MakerspaceMachineTypePricing",
    "PrintingCutoverRepair",
    "PrintingCutoverState",
    "RoleMachineScope",
    "RoleMachineTypeScope",
    "ServiceBucket",
    "ServiceQueue",
    "ServiceRequestConsumption",
    "ServiceRequestFile",
    "get_or_create_default_bucket",
]
