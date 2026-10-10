"""Free-text printer failure reports may contain member data."""


def printer_pii_fields(field_type):
    return (field_type("devices.PrinterJob", "failure_reason", "makerspace_id", None, "source", "none"),)
