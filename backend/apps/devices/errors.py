"""Typed refusals for the enrollment protocol.

Deliberately coarse: a wrong token and an unknown enrollment are the same 403, so an
unauthenticated caller cannot probe which enrollment ids exist. Only a caller holding
the right token learns that an enrollment is spent (410) or that its key is taken (409).
"""

from rest_framework import serializers, status
from rest_framework.exceptions import APIException, PermissionDenied


class EnrollmentRejected(PermissionDenied):
    default_detail = "Enrollment credentials are invalid."
    default_code = "enrollment_rejected"


class EnrollmentGone(APIException):
    status_code = status.HTTP_410_GONE
    default_detail = "This enrollment is no longer usable."
    default_code = "enrollment_gone"


class DeviceKeyConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This key is already bound to a device."
    default_code = "device_key_conflict"


class DeviceErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
