from contextlib import contextmanager

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_makerspace_profile import (
    MakerspaceProfileSerializer, ProfileErrorSerializer, ProfileGateErrorSerializer,
    profile_payload,
)
from apps.makerspaces.profile_settings import write_profile
from apps.makerspaces.servability import servable_queryset
from apps.openapi_errors import errors
from apps.payments.models import MakerspacePaymentSettings


class _SettingsCreatedDuringLock(Exception):
    """Retry with the existing settings row first, preserving the lock order."""


class MakerspaceProfileView(APIView):
    """Core configuration: usable even with every optional module switched off."""

    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def _queryset(self, request):
        return rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE,
                                    servable_queryset(), field="id")

    def handle_exception(self, exc):
        if isinstance(exc, ParseError):
            return Response({"code": "invalid_profile", "detail": "Check the profile fields.",
                             "fields": {"non_field_errors": [str(exc.detail)]}}, status=400)
        return super().handle_exception(exc)

    @contextmanager
    def _locked_rows(self, request, makerspace_id, *, create_payment=False):
        while True:
            try:
                with transaction.atomic():
                    scoped = self._queryset(request)
                    makerspace = get_object_or_404(scoped, pk=makerspace_id)
                    # Payment settings writers already lock settings before their
                    # joined makerspace. Match that order to avoid a deadlock.
                    payments = rbac.scope_by_action(
                        request.user, rbac.Action.MANAGE_MAKERSPACE,
                        MakerspacePaymentSettings.objects.filter(makerspace=makerspace),
                    )
                    if create_payment:
                        # Insert before the root lock. A concurrent settings creator
                        # needs its FK key-share lock on that root to finish inserting.
                        # Holding FOR UPDATE first could deadlock on the unique index.
                        try:
                            with transaction.atomic():
                                payments.get_or_create(makerspace=makerspace)
                        except DjangoValidationError:
                            # save() runs full_clean(): a competing insert may surface
                            # as a uniqueness validation error before the DB constraint.
                            if not payments.exists():
                                raise
                    payment = payments.select_for_update().first()
                    makerspace = get_object_or_404(scoped.select_for_update(), pk=makerspace_id)
                    if payment is None and payments.exists():
                        # Another creator committed while we waited for the root.
                        # Roll back this savepoint (releasing its root lock), then
                        # restart with settings first rather than invert the order.
                        raise _SettingsCreatedDuringLock
                    yield makerspace, payment or MakerspacePaymentSettings(makerspace=makerspace)
                    return
            except _SettingsCreatedDuringLock:
                continue

    @extend_schema(
        tags=["Admin makerspaces"], summary="Read location and opening hours",
        responses={200: MakerspaceProfileSerializer, **errors(401, 403, 404)},
    )
    def get(self, request, makerspace_id):
        makerspace = get_object_or_404(self._queryset(request), pk=makerspace_id)
        payments = rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE,
                                       MakerspacePaymentSettings.objects.filter(makerspace=makerspace))
        return Response(profile_payload(makerspace, payments.first() or MakerspacePaymentSettings(makerspace=makerspace)))

    @extend_schema(
        tags=["Admin makerspaces"], summary="Update location and opening hours",
        description=("Requires manage_makerspace. Empty hours mean always open. "
                     "Dated exceptions replace weekly hours. Currency updates the existing "
                     "payment default, never currencies on existing charges."),
        request=MakerspaceProfileSerializer,
        responses={200: MakerspaceProfileSerializer, 400: ProfileErrorSerializer,
                   423: OpenApiResponse(ProfileGateErrorSerializer, description="Tenant writes are frozen for migration."),
                   503: OpenApiResponse(ProfileGateErrorSerializer, description="The source gate cannot prove writes are safe."),
                   **errors(401, 403, 404)},
    )
    def patch(self, request, makerspace_id):
        # Check scope before validation, then validate before creating any rows.
        get_object_or_404(self._queryset(request), pk=makerspace_id)
        serializer = MakerspaceProfileSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({"code": "invalid_profile", "detail": "Check the profile fields.",
                             "fields": serializer.errors}, status=400)
        values = serializer.validated_data
        default = MakerspacePaymentSettings._meta.get_field("default_currency").get_default()
        create_payment = "default_currency" in values and values["default_currency"] != default
        with self._locked_rows(request, makerspace_id, create_payment=create_payment) as (makerspace, payment):
            try:
                write_profile(request.user, makerspace, values, payment)
            except DjangoValidationError as exc:
                transaction.set_rollback(True)
                return Response({"code": "invalid_profile", "detail": "Check the profile fields.",
                                 "fields": exc.message_dict}, status=400)
            return Response(profile_payload(makerspace, payment))
