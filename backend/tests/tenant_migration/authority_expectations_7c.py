"""Independent literal authority expectations for the label adapter."""
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D

LABEL_EXPECTED = {
    ("devices.DeviceCommand", "acknowledged_at"): (D.RESET,),
    ("devices.LabelPrintCommand", "result"): (D.PRESERVE,),
    ("devices.LabelPrintCommand", "request_id"): (D.PRESERVE,),
    ("devices.LabelPrintResult", "operation_id"): (D.PRESERVE,),
    ("devices.LabelPrintResult", "response_command_status"): (D.PRESERVE,),
}
