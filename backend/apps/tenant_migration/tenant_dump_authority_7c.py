"""Result identity/history travels; it cannot execute a cancelled parent command."""
from .tenant_dump_types import AuthorityDisposition as D, authority

LABEL_AUTHORITY_ENTRIES = (
    (("devices.DeviceCommand", "acknowledged_at"), authority(D.RESET,
        "Acknowledged delivery ownership is deployment-local and reset on import.")),
    (("devices.LabelPrintCommand", "result"), authority(D.PRESERVE,
        "Historical print outcome; parent command imports cancelled and never replays.")),
    (("devices.LabelPrintCommand", "request_id"), authority(D.PRESERVE,
        "Inert staff idempotency identity; an imported request cannot queue another print.")),
    (("devices.LabelPrintResult", "operation_id"), authority(D.PRESERVE,
        "Historical receipt identity; reading it never applies a print effect.")),
    (("devices.LabelPrintResult", "response_command_status"), authority(D.PRESERVE,
        "Snapshot of the source response, never the target delivery state.")),
)
