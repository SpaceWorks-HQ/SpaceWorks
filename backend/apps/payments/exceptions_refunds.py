"""Typed refund errors shared by the core ledger and the online rail."""

from rest_framework.exceptions import APIException


class RefundNotAllowed(APIException):
    status_code = 400

    def __init__(self, detail, code="refund_not_allowed"):
        self.detail = {"detail": detail, "code": code}


class RefundProviderFailure(APIException):
    status_code = 502

    def __init__(self, refund):
        self.detail = {
            "detail": "The payment provider rejected the refund.",
            "code": "refund_provider_failed", "refund_id": refund.pk,
        }
