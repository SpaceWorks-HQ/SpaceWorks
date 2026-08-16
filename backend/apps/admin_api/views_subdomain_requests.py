from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.makerspaces import domain_verification, provisioning
from apps.makerspaces.models import Makerspace, SubdomainRequest
from apps.makerspaces.servability import servable_queryset


class SubdomainRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubdomainRequest
        fields = [
            "id",
            "requested_label",
            "status",
            "note",
            "decided_at",
            "created_at",
        ]
        read_only_fields = ["id", "status", "note", "decided_at", "created_at"]


class SubdomainRequestErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class SubdomainRequestListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = SubdomainRequestSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_action(
            self.request.user,
            rbac.Action.MANAGE_MAKERSPACE,
            makerspace_id,
        )
        return SubdomainRequest.objects.filter(makerspace_id=makerspace_id)

    @extend_schema(
        tags=["Admin hosting"],
        summary="List platform subdomain requests for a makerspace",
        responses={
            200: SubdomainRequestSerializer(many=True),
            403: OpenApiResponse(response=SubdomainRequestErrorSerializer),
            404: OpenApiResponse(response=SubdomainRequestErrorSerializer),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin hosting"],
        summary="Request a platform subdomain for a makerspace",
        request=SubdomainRequestSerializer,
        responses={
            201: SubdomainRequestSerializer,
            400: OpenApiResponse(response=SubdomainRequestErrorSerializer),
            403: OpenApiResponse(response=SubdomainRequestErrorSerializer),
            404: OpenApiResponse(response=SubdomainRequestErrorSerializer),
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def create(self, request, makerspace_id, *args, **kwargs):
        visible_makerspaces = rbac.scope_by_action(
            request.user,
            rbac.Action.MANAGE_MAKERSPACE,
            servable_queryset(),
            field="id",
        )
        makerspace = get_object_or_404(visible_makerspaces, pk=makerspace_id)
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)

        if domain_verification.is_self_host():
            raise ValidationError("Subdomains are only available on managed hosting.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        normalized = serializer.validated_data["requested_label"].strip().lower()
        if "." in normalized or not provisioning.LABEL_RE.fullmatch(normalized):
            raise ValidationError("Enter a valid single subdomain label.")
        if normalized in provisioning.RESERVED_LABELS:
            raise ValidationError("This subdomain label is reserved.")

        platform_suffix = str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip().lower()
        current_domain = (makerspace.frontend_domain or "").lower()
        if current_domain and current_domain.endswith(platform_suffix):
            raise ValidationError("This space already has a subdomain.")

        target = f"{normalized}{platform_suffix}"
        if Makerspace.objects.filter(frontend_domain__iexact=target).exists():
            raise ValidationError("That subdomain is already taken.")

        try:
            with transaction.atomic():
                subdomain_request = SubdomainRequest.objects.create(
                    makerspace=makerspace,
                    requested_label=normalized,
                    requested_by=request.user,
                )
        except IntegrityError as exc:
            raise ValidationError(
                "You already have a pending subdomain request."
            ) from exc

        audit.record(
            request.user,
            "makerspace.subdomain_requested",
            makerspace=makerspace,
            target=subdomain_request,
            meta={"requested_label": normalized},
        )
        return Response(
            self.get_serializer(subdomain_request).data,
            status=status.HTTP_201_CREATED,
        )
