import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts import rbac
from apps.admin_api.api_client_serializers import (
    ApiClientSerializer,
    ApiClientCreateResponseSerializer,
)
from apps.admin_api.api_key_request_views import (
    ApiKeyRequestListCreateView as ApiKeyRequestListCreateView,
)
from apps.admin_api.permissions import IsActiveStaff
from apps.apiclients.models import ApiClient
from apps.apiclients.services import sync_makerspace_origins
from apps.audit import services as audit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace


ERRORS = {401: ErrorSerializer, 403: ErrorSerializer, 404: ErrorSerializer}


def _visible_makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_MAKERSPACE,
            Makerspace.objects.all(),
            field="id",
        ),
        pk=makerspace_id,
    )
    if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def _visible_clients(actor):
    return rbac.scope_by_visibility_or_action(
        actor, rbac.Action.MANAGE_MAKERSPACE, ApiClient.objects.all()
    )


def _related_makerspace(makerspace_id):
    if makerspace_id is None:
        return None
    return Makerspace.objects.get(pk=makerspace_id)


@extend_schema_view(
    get=extend_schema(responses={200: ApiClientSerializer(many=True), **ERRORS}),
    post=extend_schema(responses={201: ApiClientCreateResponseSerializer, **ERRORS}),
)
@extend_schema(tags=["API clients"], summary="List or create makerspace API clients")
class ApiClientListCreateView(generics.ListCreateAPIView):
    serializer_class = ApiClientSerializer
    permission_classes = [IsActiveStaff]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["makerspace_id"] = self.kwargs.get("makerspace_id")
        return context

    def get_queryset(self):
        makerspace = _visible_makerspace(
            self.request.user, self.kwargs["makerspace_id"]
        )
        return (
            ApiClient.objects.select_related("makerspace")
            .filter(makerspace=makerspace)
            .order_by("label")
        )

    def create(self, request, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, self.kwargs["makerspace_id"])
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
                    scopes=serializer.validated_data["scopes"],
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
            meta={
                "allowed_origins": client.allowed_origins,
                "scopes": client.scopes,
            },
        )
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(responses={200: ApiClientSerializer, **ERRORS}),
    patch=extend_schema(responses={200: ApiClientSerializer, **ERRORS}),
    delete=extend_schema(responses={204: None, **ERRORS}),
)
@extend_schema(tags=["API clients"], summary="Retrieve, update, or delete API client")
class ApiClientDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ApiClientSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return _visible_clients(self.request.user).select_related("makerspace")

    def get_object(self):
        instance = super().get_object()
        if not rbac.can(
            self.request.user,
            rbac.Action.MANAGE_MAKERSPACE,
            instance.makerspace_id,
        ):
            raise PermissionDenied()
        return instance

    def perform_update(self, serializer):
        previous_scopes = list(serializer.instance.scopes)
        changing_scopes = "scopes" in serializer.validated_data
        changing_scope_ceiling = (
            changing_scopes or "client_type" in serializer.validated_data
        )
        with transaction.atomic():
            if changing_scope_ceiling:
                # Do not join the nullable makerspace FK in this FOR UPDATE query.
                serializer.instance = ApiClient.objects.select_for_update().get(
                    pk=serializer.instance.pk
                )
                previous_scopes = list(serializer.instance.scopes)
                makerspace = _related_makerspace(serializer.instance.makerspace_id)
                serializer.instance.makerspace = makerspace
                # is_valid() ran before the lock. Check the combined incoming values
                # against the row state that will actually be persisted.
                serializer.validate_client_type_scope_ceiling(
                    serializer.validated_data
                )
            else:
                makerspace = serializer.instance.makerspace
            reactivating = (
                not serializer.instance.is_active
                and serializer.validated_data.get("is_active") is True
            )
            if reactivating and makerspace is not None:
                limits.check_quota(makerspace, "api_clients", adding=1)
            instance = serializer.save()
            if changing_scopes and previous_scopes != instance.scopes:
                audit.record(
                    self.request.user,
                    "api_client.scopes_changed",
                    makerspace=makerspace,
                    target=instance,
                    meta={"previous_scopes": previous_scopes, "scopes": instance.scopes},
                )
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
    responses={200: ApiClientCreateResponseSerializer, **ERRORS},
)
class ApiClientRotateSecretView(generics.GenericAPIView):
    serializer_class = ApiClientSerializer
    permission_classes = [IsActiveStaff]

    def get_queryset(self):
        return _visible_clients(self.request.user)

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            client = get_object_or_404(
                self.get_queryset().select_for_update(of=("self",)),
                pk=self.kwargs["pk"],
            )
            if not rbac.can(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                client.makerspace_id,
            ):
                raise PermissionDenied()
            client.makerspace = _related_makerspace(client.makerspace_id)
            self.check_object_permissions(request, client)
            current_secret = client.get_secret()
            raw_secret = secrets.token_urlsafe(32)
            while secrets.compare_digest(raw_secret, current_secret):
                raw_secret = secrets.token_urlsafe(32)
            grace_expires_at = timezone.now() + timedelta(hours=24)
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
