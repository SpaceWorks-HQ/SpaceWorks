"""Compatibility import surface for the self-checkout workflows."""

from collections import Counter

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.hardware_requests.self_checkout_evidence import _lock_unused_evidence, _public_evidence
from apps.hardware_requests.self_checkout_helpers import (
    _checkout_box,
    _checkout_target,
    _create_issued_request,
    _eligible_asset,
    _eligible_product,
    _issue_product,
    _issued_request,
    _locked_qr,
    _return_request_items,
)
from apps.hardware_requests.self_checkout_issue import checkout_tool, qr_has_active_loan
from apps.hardware_requests.self_checkout_returns import return_tool
from apps.hardware_requests.workflow_errors import InvalidTransition, RequestValidationError
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct


__all__ = [
    "Box",
    "Counter",
    "HardwareRequest",
    "HardwareRequestItem",
    "InventoryAsset",
    "InventoryProduct",
    "InvalidTransition",
    "PublicToolLoan",
    "Q",
    "QrCode",
    "QrScanEvent",
    "RequestValidationError",
    "_checkout_box",
    "_checkout_target",
    "_create_issued_request",
    "_eligible_asset",
    "_eligible_product",
    "_issue_product",
    "_issued_request",
    "_locked_qr",
    "_return_request_items",
    "audit",
    "availability",
    "checkout_tool",
    "qr_has_active_loan",
    "return_tool",
    "timezone",
    "transaction",
]
