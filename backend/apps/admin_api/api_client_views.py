import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.api_client_serializers import (
    ApiClientSerializer,
    ApiClientCreateResponseSerializer,
    ApiKeyRequestSerializer,
    ApiIntegrationSettingsSerializer,
)
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.apiclients.services import sync_makerspace_origins
from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.servability import is_servable


API_CLIENT_SECRET_ROTATION_GRACE_PERIOD = timedelta(hours=24)


@extend_schema(tags=["API clients"], summary="List or create makerspace API clients")
class ApiClientListCreateView(generics.ListCreateAPIView):
    serializer_class = ApiClientSerializer
    permission_classes = [IsActiveStaff]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["makerspace_id"] = self.kwargs.get("makerspace_id")
        return context

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_action(
            self.request.user,
            rbac.Action.MANAGE_MAKERSPACE,
            makerspace_id,
        )
        return (
            ApiClient.objects.select_related("makerspace")
            .filter(makerspace_id=makerspace_id)
            .order_by("label")
        )

    @extend_schema(responses={201: ApiClientCreateResponseSerializer})
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        makerspace_id = self.kwargs["makerspace_id"]
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
        makerspace = get_object_or_404(Makerspace, pk=makerspace_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                limits.check_quota(makerspace, "api_clients", adding=1)
                client, secret = ApiClient.issue(
                    label=serializer.validated_data["label"],
                    makerspace=makerspace,
                    allowed_origins=serializer.validated_data["allowed_origins"],
                    created_by=request.user,
                    client_type=serializer.validated_data.get("client_type", "server"),
                    scopes=serializer.validated_data.get("scopes") or [],
                    rate_limit_tier=serializer.validated_data.get(
                        "rate_limit_tier", "standard"
                    ),
                )
        except DjangoValidationError as exc:
            raise ValidationError(getattr(exc, "message_dict", exc.messages)) from exc
        client.is_active = serializer.validated_data.get("is_active", True)
        client.save(update_fields=["is_active", "updated_at"])
        sync_makerspace_origins(makerspace)
        data = self.get_serializer(client).data
        data["client_secret"] = secret
        audit.record(
            request.user,
            "api_client.created",
            makerspace=makerspace,
            target=client,
            meta={"allowed_origins": client.allowed_origins},
        )
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["API clients"], summary="Retrieve, update, or delete API client")
class ApiClientDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ApiClientSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return rbac.scope_by_action(
            self.request.user,
            rbac.Action.MANAGE_MAKERSPACE,
            ApiClient.objects.select_related("makerspace"),
        )

    def perform_update(self, serializer):
        makerspace = serializer.instance.makerspace
        reactivating = (
            not serializer.instance.is_active
            and serializer.validated_data.get("is_active") is True
        )
        with transaction.atomic():
            if reactivating:
                limits.check_quota(makerspace, "api_clients", adding=1)
            instance = serializer.save()
        sync_makerspace_origins(instance.makerspace)
        audit.record(
            self.request.user,
            "api_client.updated",
            makerspace=instance.makerspace,
            target=instance,
        )

    def perform_destroy(self, instance):
        makerspace = instance.makerspace
        audit.record(
            self.request.user,
            "api_client.deleted",
            makerspace=makerspace,
            target=instance,
        )
        instance.delete()
        sync_makerspace_origins(makerspace)


@extend_schema(
    tags=["API clients"],
    summary="Rotate API client secret",
    request=None,
    responses={200: ApiClientCreateResponseSerializer},
)
class ApiClientRotateSecretView(generics.GenericAPIView):
    serializer_class = ApiClientSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        return rbac.scope_by_action(
            self.request.user,
            rbac.Action.MANAGE_MAKERSPACE,
            ApiClient.objects.select_related("makerspace"),
        )

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            client = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)),
                pk=self.kwargs["pk"],
            )
            self.check_object_permissions(request, client)
            current_secret = client.get_secret()
            raw_secret = secrets.token_urlsafe(32)
            while secrets.compare_digest(raw_secret, current_secret):
                raw_secret = secrets.token_urlsafe(32)
            grace_expires_at = timezone.now() + API_CLIENT_SECRET_ROTATION_GRACE_PERIOD
            client.previous_secret_encrypted = client.secret_encrypted
            client.previous_secret_valid_until = grace_expires_at
            client.set_secret(raw_secret)
            client.save(
                update_fields=[
                    "secret_encrypted",
                    "previous_secret_encrypted",
                    "previous_secret_valid_until",
                    "updated_at",
                ]
            )
            audit.record(
                request.user,
                "api_client.secret_rotated",
                makerspace=client.makerspace,
                target=client,
                meta={
                    "grace_window_opened": True,
                    "previous_secret_valid_until": grace_expires_at.isoformat(),
                },
            )
        data = ApiClientSerializer(client, context=self.get_serializer_context()).data
        data["client_secret"] = raw_secret
        return Response(data)


@extend_schema(
    tags=["API key requests"],
    summary="List or create API key requests",
    parameters=[OpenApiParameter("makerspace", int, OpenApiParameter.QUERY)],
)
class ApiKeyRequestListCreateView(generics.ListCreateAPIView):
    serializer_class = ApiKeyRequestSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        queryset = (
            ApiKeyRequest.objects.select_related("makerspace", "requester")
            .filter(requester=self.request.user)
            .order_by("-created_at")
        )
        makerspace_id = self.request.query_params.get("makerspace")
        if makerspace_id:
            queryset = queryset.filter(makerspace_id=makerspace_id)
        return queryset

    def perform_create(self, serializer):
        makerspace = serializer.validated_data["makerspace"]
        # Any active staff MEMBER of the makerspace may file a request (incl. print/guest
        # admins who lack VIEW_INVENTORY) - issuance still happens only in the superadmin
        # /control/ admin. Gate on membership existence, not a specific action.
        user = self.request.user
        is_superadmin = user.is_superuser or user.role == User.Role.SUPERADMIN
        is_member = MakerspaceMembership.objects.filter(
            user=user, makerspace_id=makerspace.id, status="active"
        ).exists()
        if not is_servable(makerspace):
            raise PermissionDenied()
        if is_superadmin and not is_member:
            require_action(user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id)
        elif not is_member:
            raise PermissionDenied()

        api_key_request = serializer.save(
            requester=self.request.user,
            status=ApiKeyRequest.Status.PENDING,
        )
        audit.record(
            self.request.user,
            "api_key_request.created",
            makerspace=makerspace,
            target=api_key_request,
            meta={"allowed_origins": api_key_request.allowed_origins},
        )


@extend_schema(tags=["API clients"], summary="Retrieve or update API integration settings")
class ApiIntegrationSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = ApiIntegrationSettingsSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_action(self.request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
        return get_object_or_404(Makerspace, pk=makerspace_id)

    def perform_update(self, serializer):
        instance = serializer.save()
        audit.record(
            self.request.user,
            "api_integration.updated",
            makerspace=instance,
            target=instance,
        )
