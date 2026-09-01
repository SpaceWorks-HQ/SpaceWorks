from drf_spectacular.utils import OpenApiExample, OpenApiParameter


PUBLISHABLE_KEY_PARAMETER = OpenApiParameter(
    name="X-Publishable-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=False,
    description=(
        "Public API key for a makerspace public client. Required when "
        "API_CLIENT_AUTH_REQUIRED is enabled."
    ),
)

API_CLIENT_NONCE_PARAMETER = OpenApiParameter(
    name="X-Nonce",
    type=str,
    location=OpenApiParameter.HEADER,
    required=False,
    description=(
        "Unique, unpredictable nonce for HMAC-authenticated server API clients "
        "(1-128 characters: letters, digits, `.`, `_`, `~`, or `-`). Include it "
        "between `X-Timestamp` and the raw body in the signed bytes: "
        "`METHOD\\nFULL_PATH\\nTIMESTAMP\\nNONCE\\nBODY`. It is optional only for "
        "publishable-key/browser authentication and during the temporary legacy "
        "rollout while `APICLIENT_REQUIRE_NONCE` is disabled."
    ),
)

# A LIST, not a tuple: drf-spectacular's get_override_parameters does
# `super().get_override_parameters() + parameters`, so a tuple raises
# "can only concatenate list (not tuple) to list" and breaks schema generation outright.
PUBLIC_API_AUTH_PARAMETERS = [
    PUBLISHABLE_KEY_PARAMETER,
    API_CLIENT_NONCE_PARAMETER,
]

PUBLIC_REQUEST_SUBMIT_EXAMPLE = OpenApiExample(
    "Submit public equipment request",
    value={
        "requester_name": "Shaan Shoukath",
        "contact_email": "shaans@example.com",
        "contact_phone": "+919876543210",
        "requested_for": "Electronics workshop diagnostics",
        "items": [{"product_id": 42, "quantity": 2}],
    },
    request_only=True,
)

PUBLIC_REQUEST_LOOKUP_EXAMPLE = OpenApiExample(
    "Lookup requests by Check-In email or phone",
    value={"identifier": "shaans@example.com"},
    request_only=True,
)

PUBLIC_REQUEST_STATUS_EXAMPLE = OpenApiExample(
    "Public request status",
    value={
        "public_token": "4f2b93e1-6ef4-41c2-8407-7f26bb3b2d8f",
        "requested_for": "Electronics workshop diagnostics",
        "status": "pending_approval",
        "rejection_reason": "",
        "created_at": "2026-06-11T10:30:00Z",
        "items": [{"product_name": "Soldering Iron", "requested_quantity": 2}],
    },
    response_only=True,
)

BULK_IMPORT_ROWS_EXAMPLE = OpenApiExample(
    "Preview inventory rows",
    value={
        "rows": [
            {
                "name": "Soldering Iron",
                "total_quantity": 10,
                "available_quantity": 8,
                "is_public": True,
            }
        ],
        "mapping": {"name": "name", "total_quantity": "total_quantity"},
    },
    request_only=True,
)

RESTRICT_USER_EXAMPLE = OpenApiExample(
    "Restrict a requester",
    value={"status": "restricted", "reason": "Unreturned loan under review"},
    request_only=True,
)

QR_BOX_EXAMPLE = OpenApiExample(
    "Create a QR-coded box",
    value={
        "makerspace_id": 1,
        "label": "Electronics Box A",
        "location": "Bench Storage",
        "description": "Issued hardware kit box",
    },
    request_only=True,
)

QR_SCAN_EXAMPLE = OpenApiExample(
    "Scan QR during issue",
    # The payload is the opaque 32-char hex token printed on the physical QR label
    # (uuid4().hex) - the same value stored as QrCode.payload / Box.code.
    value={"payload": "3f9a1c2b4d5e6f7081920a1b2c3d4e5f", "context": "issue", "request_id": 99},
    request_only=True,
)

QR_RESOLVE_REQUEST_EXAMPLE = OpenApiExample(
    "Resolve a scanned QR payload",
    # `payload` is exactly the opaque string encoded in the QR image - a 32-char
    # lowercase hex token (Python uuid4().hex). It is NOT a URL or JSON; the scanner
    # reads this raw string off the label and posts it here to resolve the target.
    value={"payload": "3f9a1c2b4d5e6f7081920a1b2c3d4e5f"},
    request_only=True,
)

QR_RESOLVE_RESPONSE_EXAMPLE = OpenApiExample(
    "Resolved box QR",
    value={
        "qr": {
            "id": 12,
            "makerspace": 1,
            "payload": "3f9a1c2b4d5e6f7081920a1b2c3d4e5f",
            "target_type": "box",
            "target_id": 5,
            "status": "active",
            "created_at": "2026-06-27T09:30:00Z",
            "updated_at": "2026-06-27T09:30:00Z",
            "revoked_at": None,
        },
        "target": {"type": "box", "id": 5, "label": "Electronics Box A", "code": "3f9a1c2b4d5e6f7081920a1b2c3d4e5f"},
        # Sorted, deduped action set as emitted by _allowed_scanner_actions for a
        # QR-manager scanning an active box (scanner module on).
        "allowed_actions": ["contents", "move_container", "record_scan", "revoke", "view"],
    },
    response_only=True,
)

PUBLIC_TOOL_SCAN_EXAMPLE = OpenApiExample(
    "Public QR tool return scan",
    value={
        "identifier": "shaans@example.com",
        "payload": "BOX-ABC123",
        "evidence_id": 123,
        "remark": "Returned to the electronics shelf in good condition.",
    },
    request_only=True,
)

PUBLIC_TOOL_CHECKOUT_EXAMPLE = OpenApiExample(
    "Public QR tool checkout",
    value={
        "payload": "BOX-ABC123",
        "requester_name": "Shaan Shoukath",
        "contact_email": "shaans@example.com",
        "contact_phone": "+919876543210",
        "evidence_id": 122,
        "remark": "Borrowing for electronics workshop diagnostics.",
    },
    request_only=True,
)

LOGIN_EXAMPLE = OpenApiExample(
    "Staff login",
    value={"username": "admin", "password": "secret-password", "surface": "staff"},
    request_only=True,
)
