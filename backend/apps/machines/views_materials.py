from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import transaction, IntegrityError
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.apiclients.throttling import ClientTierRateThrottle
from apps.admin_api.permissions import IsActiveStaff
from apps.audit.services import record
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module_for_servable, require_module
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import feature_enabled
from apps.makerspaces.models import Makerspace
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS
from .models import MachineType
from .models_materials import MachineMaterial, validate_colours
from .material_catalogue import catalogue
from .intake import validate_intake_schema

ERRORS = {code: ErrorSerializer for code in (401, 403, 404, 423, 429, 503)}
ERRORS[400] = {"type": "object", "additionalProperties": True}


def type_for(space, pk):
    owned = rbac.scope_verified_tenant(MachineType.objects.all(), space)
    return get_object_or_404(owned | MachineType.objects.filter(makerspace__isnull=True), pk=pk)


def managed_space(actor, pk, feature="machines.material_catalogue"):
    space = get_object_or_404(rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE,
                               Makerspace.objects.all(), field="id"), pk=pk)
    require_module(space, "machines")
    if not feature_enabled(space, feature):
        raise ValidationError({"detail": "This machine feature is disabled."})
    if not rbac.is_space_manager_identity(actor, space.pk):
        raise PermissionDenied()
    return space


class MaterialSerializer(serializers.ModelSerializer):
    colours = serializers.JSONField(required=True, validators=[validate_colours])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        space = self.context.get("space")
        if space is None:
            self.fields["machine_type"].queryset = MachineType.objects.none()
            return
        self.fields["machine_type"].queryset = (
            rbac.scope_verified_tenant(MachineType.objects.all(), space) |
            MachineType.objects.filter(makerspace__isnull=True)
        )

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object.")
        unknown = set(data) - {name for name, field in self.fields.items() if not field.read_only}
        if unknown:
            raise serializers.ValidationError({name: "Unexpected field." for name in sorted(unknown)})
        return super().to_internal_value(data)

    class Meta:
        model = MachineMaterial
        fields = ("id", "machine_type", "name", "colours", "is_active")
        read_only_fields = ("id",)

    def validate(self, attrs):
        space = self.context["space"]
        machine_type = attrs.get("machine_type", getattr(self.instance, "machine_type", None))
        name = attrs.get("name", getattr(self.instance, "name", ""))
        rows = rbac.scope_by_action(self.context["request"].user, rbac.Action.MANAGE_MAKERSPACE,
                                   MachineMaterial.objects.all()).filter(makerspace=space, machine_type=machine_type, name__iexact=name)
        if self.instance:
            rows = rows.exclude(pk=self.instance.pk)
        if rows.exists():
            raise serializers.ValidationError({"name": "This material already exists for this machine type."})
        return attrs

    def validate_machine_type(self, value):
        if value.makerspace_id not in (None, self.context["space"].pk):
            raise serializers.ValidationError("Machine type belongs to another makerspace.")
        return value


class IntakeSerializer(serializers.Serializer):
    intake_schema = serializers.JSONField()

    def to_internal_value(self, data):
        from collections.abc import Mapping
        if not isinstance(data, Mapping) or set(data) - {"intake_schema"}:
            raise serializers.ValidationError("Only intake_schema is accepted.")
        return super().to_internal_value(data)

    def validate_intake_schema(self, value):
        try:
            validate_intake_schema(value)
        except ModelValidationError as exc:
            raise serializers.ValidationError(getattr(exc, "messages", [str(exc)])) from exc
        return value


class PublicIntakeSerializer(serializers.Serializer):
    materials = MaterialSerializer(many=True)
    intake_schema = serializers.JSONField()


class PublicMaterialSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    colours = serializers.ListField(child=serializers.CharField())


class PublicTypeIntakeSerializer(serializers.Serializer):
    materials = PublicMaterialSerializer(many=True)
    intake_schema = serializers.JSONField()


class PublicTypeIntakeView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(auth=[], request=None, parameters=PUBLIC_API_AUTH_PARAMETERS, responses={200: PublicTypeIntakeSerializer, **ERRORS})
    def get(self, request, makerspace_slug, type_id):
        space = get_public_makerspace(makerspace_slug)
        require_module_for_servable(space, "machines")
        require_module_for_servable(space, "machine_service")
        from apps.makerspaces.editions import require_public_surface
        require_public_surface("machines")
        if not space.public_inventory_enabled:
            raise ValidationError({"detail": "Public site is disabled."})
        machine_type = type_for(space, type_id)
        from .models import Machine
        published = rbac.scope_public_catalogue(Machine.objects.all(), space).filter(
            machine_type=machine_type, is_active=True, is_public=True).exists()
        from .printer_capabilities import is_printer_type
        from apps.makerspaces.platform import module_enabled
        if not published and is_printer_type(machine_type) and module_enabled(space, "printing"):
            from .public_printer_service import public_queues
            published = public_queues(space).exists()
        if not published:
            raise NotFound()
        return Response({"materials": catalogue(space, machine_type), "intake_schema":
                         machine_type.intake_schema if feature_enabled(space, "machines.structured_intake") else {}})


class MaterialListView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = MaterialSerializer

    def get_queryset(self):
        space = managed_space(self.request.user, self.kwargs["makerspace_id"])
        rows = rbac.scope_by_action(self.request.user, rbac.Action.MANAGE_MAKERSPACE,
                                    MachineMaterial.objects.all()).filter(makerspace=space)
        if value := self.request.query_params.get("machine_type_id"):
            try:
                type_id = int(value)
                if type_id <= 0:
                    raise ValueError()
            except ValueError as exc:
                raise ValidationError({"machine_type_id": "Enter a positive identifier."}) from exc
            rows = rows.filter(machine_type=type_for(space, type_id))
        return rows.order_by("name", "pk")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "space": managed_space(self.request.user, self.kwargs["makerspace_id"])}

    @extend_schema(request=None, parameters=[OpenApiParameter("machine_type_id", int)], responses={200: MaterialSerializer(many=True), **ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=MaterialSerializer, responses={201: MaterialSerializer, **ERRORS})
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        space = serializer.context["space"]
        try:
            row = serializer.save(makerspace=space)
        except IntegrityError as exc:
            raise ValidationError({"name": "This material already exists for this machine type."}) from exc
        record(self.request.user, "machine.material_created", makerspace=space, target=row)


class MaterialDetailView(MaterialListView, generics.RetrieveUpdateDestroyAPIView):
    http_method_names = ["get", "patch", "delete", "head", "options"]

    @extend_schema(request=None, responses={200: MaterialSerializer, **ERRORS})
    def get(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    @extend_schema(request=MaterialSerializer, responses={200: MaterialSerializer, **ERRORS})
    def patch(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @extend_schema(request=None, responses={204: None, **ERRORS})
    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)

    @transaction.atomic
    def perform_update(self, serializer):
        try:
            row = serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"name": "This material already exists for this machine type."}) from exc
        record(self.request.user, "machine.material_updated", makerspace=row.makerspace, target=row)

    @transaction.atomic
    def perform_destroy(self, instance):
        record(self.request.user, "machine.material_deleted", makerspace=instance.makerspace, target=instance)
        instance.delete()
