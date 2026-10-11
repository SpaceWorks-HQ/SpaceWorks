from collections.abc import Mapping

from django.shortcuts import get_object_or_404
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, generics
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit.services import record
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled
from .models_stocktake_discipline import StocktakePolicy, StocktakeSchedule


def space_for(actor, pk):
    space = get_object_or_404(rbac.scope_by_action(actor, rbac.Action.EDIT_INVENTORY,
                               Makerspace.objects.all(), field="id"), pk=pk)
    require_module(space, "stocktake")
    require_action(actor, rbac.Action.EDIT_INVENTORY, pk)
    if not feature_enabled(space, "stocktake.discipline"):
        raise ValidationError({"detail": "Stocktake discipline is disabled."})
    return space


class StrictModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object.")
        unknown = set(data) - {name for name, field in self.fields.items() if not field.read_only}
        if unknown:
            raise serializers.ValidationError({name: "Unexpected field." for name in sorted(unknown)})
        return super().to_internal_value(data)


class PolicySerializer(StrictModelSerializer):
    class Meta:
        model = StocktakePolicy
        fields = ("blind_default", "variance_threshold")


class ScheduleSerializer(StrictModelSerializer):
    interval_days = serializers.IntegerField(min_value=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "request" not in self.context or "space" not in self.context:
            self.fields["container"].queryset = self.fields["container"].queryset.none()
            return
        actor = self.context["request"].user
        self.fields["container"].queryset = rbac.scope_by_action(
            actor, rbac.Action.EDIT_INVENTORY, self.fields["container"].queryset,
        ).filter(makerspace=self.context["space"])

    class Meta:
        model = StocktakeSchedule
        fields = ("id", "name", "container", "interval_days", "next_due", "blind", "is_active")
        read_only_fields = ("id",)

    def validate_container(self, value):
        if value and value.makerspace_id != self.context["space"].pk:
            raise serializers.ValidationError("Container belongs to another makerspace.")
        return value


ERRORS = {code: ErrorSerializer for code in (401, 403, 404, 423, 429, 503)}
ERRORS[400] = {"type": "object", "additionalProperties": True}


class StocktakePolicyView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(request=None, responses={200: PolicySerializer, **ERRORS})
    def get(self, request, makerspace_id):
        space = space_for(request.user, makerspace_id)
        policy = rbac.scope_by_action(request.user, rbac.Action.EDIT_INVENTORY,
                                     StocktakePolicy.objects.all()).filter(makerspace=space).first()
        return Response(PolicySerializer(policy or StocktakePolicy(makerspace=space)).data)

    @extend_schema(request=PolicySerializer, responses={200: PolicySerializer, **ERRORS})
    @transaction.atomic
    def put(self, request, makerspace_id):
        space = space_for(request.user, makerspace_id)
        require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, space.pk)
        policy, _ = rbac.scope_by_action(request.user, rbac.Action.MANAGE_MAKERSPACE,
                                         StocktakePolicy.objects.all()).get_or_create(makerspace=space)
        serializer = PolicySerializer(policy, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record(request.user, "stocktake.policy_updated", makerspace=space, target=policy)
        return Response(serializer.data)


class StocktakeScheduleListView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ScheduleSerializer

    def get_queryset(self):
        space = space_for(self.request.user, self.kwargs["makerspace_id"])
        return rbac.scope_by_action(self.request.user, rbac.Action.EDIT_INVENTORY,
                                    StocktakeSchedule.objects.all()).filter(makerspace=space).order_by("next_due", "pk")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "space": space_for(self.request.user, self.kwargs["makerspace_id"])}

    @extend_schema(request=None, responses={200: ScheduleSerializer(many=True), **ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=ScheduleSerializer, responses={201: ScheduleSerializer, **ERRORS})
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    @transaction.atomic
    def perform_create(self, serializer):
        space = serializer.context["space"]
        require_action(self.request.user, rbac.Action.MANAGE_MAKERSPACE, space.pk)
        row = serializer.save(makerspace=space)
        record(self.request.user, "stocktake.schedule_created", makerspace=space, target=row)


class StocktakeScheduleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ScheduleSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        space = space_for(self.request.user, self.kwargs["makerspace_id"])
        require_action(self.request.user, rbac.Action.MANAGE_MAKERSPACE, space.pk)
        return rbac.scope_by_action(self.request.user, rbac.Action.EDIT_INVENTORY,
                                    StocktakeSchedule.objects.all()).filter(makerspace=space)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "space": space_for(self.request.user, self.kwargs["makerspace_id"])}

    @extend_schema(request=None, responses={200: ScheduleSerializer, **ERRORS})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=ScheduleSerializer, responses={200: ScheduleSerializer, **ERRORS})
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @extend_schema(request=None, responses={204: None, **ERRORS})
    def delete(self, request, *args, **kwargs):
        return super().delete(request, *args, **kwargs)

    @transaction.atomic
    def perform_update(self, serializer):
        row = serializer.save()
        record(self.request.user, "stocktake.schedule_updated", makerspace=row.makerspace, target=row)

    @transaction.atomic
    def perform_destroy(self, instance):
        record(self.request.user, "stocktake.schedule_deleted", makerspace=instance.makerspace, target=instance)
        instance.delete()
