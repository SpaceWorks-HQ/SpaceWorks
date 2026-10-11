"""Account routes distinguish DRF field errors from typed business failures."""
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers


class AccountFailureSerializer(serializers.Serializer):
    detail = serializers.CharField()
    # DRF auth/permission failures carry detail alone; domain and source-gate
    # failures also carry a stable code.
    code = serializers.CharField(required=False)


# Unknown profile keys become response keys, so additionalProperties describes
# validation more accurately than a fixed list of fields.
ACCOUNT_ERRORS = {
    400: OpenApiResponse(response={
        "type": "object", "additionalProperties": {"oneOf": [
            {"type": "string"}, {"type": "array", "items": {"type": "string"}},
        ]},
    }, description="Disabled module/feature, invalid input, or unavailable export."),
    **{code: AccountFailureSerializer for code in (401, 403, 404, 423, 429, 503)},
}
