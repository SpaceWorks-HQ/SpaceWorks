"""Remote delivery grants reset; source report identifiers remain inert history."""
from .tenant_dump_types import AuthorityDisposition as D, authority

PRINTER_AUTHORITY_ENTRIES = tuple(
    (edge, authority(D.RESET, "Remote command ownership never becomes target authority."))
    for edge in (
        ("devices.DeviceCommand", "status"), ("devices.DeviceCommand", "lease_token_digest"),
        ("devices.DeviceCommand", "lease_expires_at"), ("devices.PrinterDeviceBinding", "enabled"),
        ("devices.PrinterDeviceBinding", "auto_apply_terminal"),
    )
) + (
    (("devices.DeviceCommand", "device_key_version"), authority(D.PRESERVE, "Historical key-version pin; imported command is cancelled.")),
    (("devices.PrinterJob", "state"), authority((D.PRESERVE, D.RESET), "Keep applied/cancelled history; unprocessed source work becomes inert review.")),
    (("devices.PrinterJob", "terminal_operation_id"), authority(D.PRESERVE, "Inert source report identity, never replayed.")),
    (("devices.PrinterJob", "failure_reason"), authority(D.PRESERVE, "Tenant-owned encrypted measurement note; never audit metadata.")),
)
