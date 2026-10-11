from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.audit.services import record
from .views_materials import IntakeSerializer, ERRORS, managed_space, type_for


class MachineTypeIntakeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(request=None, responses={200: IntakeSerializer, **ERRORS})
    def get(self, request, makerspace_id, type_id):
        machine_type = type_for(managed_space(request.user, makerspace_id, "machines.structured_intake"), type_id)
        return Response({"intake_schema": machine_type.intake_schema})

    @extend_schema(request=IntakeSerializer, responses={200: IntakeSerializer, **ERRORS})
    @transaction.atomic
    def put(self, request, makerspace_id, type_id):
        space = managed_space(request.user, makerspace_id, "machines.structured_intake")
        machine_type = type_for(space, type_id)
        if machine_type.makerspace_id is None:
            raise ValidationError({"detail": "Built-in intake contracts are protected."})
        serializer = IntakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        machine_type.intake_schema = serializer.validated_data["intake_schema"]
        machine_type.save(update_fields=["intake_schema"])
        record(request.user, "machine.intake_updated", makerspace=space, target=machine_type)
        return Response(serializer.data)
