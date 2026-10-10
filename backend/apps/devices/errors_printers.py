"""Stable transport errors; never embed tracebacks or a submitted report."""
from rest_framework.exceptions import APIException


class PrinterConflict(APIException):
    status_code = 409
    default_detail = "Printer operation conflicts with its durable state."
    default_code = "printer_conflict"


class LeaseExpired(APIException):
    status_code = 410
    default_detail = "Command delivery lease expired."
    default_code = "lease_expired"
