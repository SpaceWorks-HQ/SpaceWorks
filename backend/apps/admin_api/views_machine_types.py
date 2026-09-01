from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_types import MachineTypeAccessSerializer
from apps.audit import services as audit
from apps.machines import access, role_scope
from apps.machines.models import Machine, MachineType
from apps.machines.serializers import (
    MachineTypeCreateSerializer,
    MachineTypeSerializer,
    MachineTypeUpdateSerializer,
)
from apps.makerspaces.guards import require_module


class MachineTypeListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin machines'],
        summary='List machine types for a makerspace',
        request=None,
        responses={200: MachineTypeAccessSerializer(many=True)},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        require_module(makerspace_id, 'machines')
        if not access.can_see_machines(request.user, makerspace_id):
            raise PermissionDenied()
        applicable = list(MachineType.objects.filter(
            Q(makerspace__isnull=True) | Q(makerspace_id=makerspace_id)
        ))
        manage_granted = rbac.can(
            request.user, rbac.Action.MANAGE_MACHINES, makerspace_id
        )
        machine_scope = role_scope.manage_scope_for(request.user, makerspace_id)
        direct_actions = {
            action
            for action in {row.managing_action for row in applicable if row.managing_action}
            if rbac.can(request.user, action, makerspace_id)
            and role_scope.grants_directly(request.user, makerspace_id, action)
        }

        if manage_granted and machine_scope is role_scope.EXEMPT:
            reachable_ids = {row.pk for row in applicable}
        else:
            linked_type_ids = machine_scope[0] if manage_granted else frozenset()
            reachable_ids = set(linked_type_ids)
            reachable_ids.update(
                access.scope_machines_for_actor(
                    request.user,
                    Machine.objects.filter(makerspace_id=makerspace_id),
                ).values_list("machine_type_id", flat=True)
            )
            reachable_ids.update(
                row.pk for row in applicable if row.managing_action in direct_actions
            )

        rows = [row for row in applicable if row.pk in reachable_ids]
        for row in rows:
            row.can_create_machine = (
                manage_granted
                and role_scope.scope_covers_type(machine_scope, row)
            ) or row.managing_action in direct_actions
        return Response(MachineTypeAccessSerializer(rows, many=True).data)

    @extend_schema(
        tags=['Admin machines'],
        summary='Create a custom machine type',
        request=MachineTypeCreateSerializer,
        responses={
            201: MachineTypeSerializer,
            400: OpenApiResponse(description='Invalid machine type.'),
        },
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        require_module(makerspace_id, 'machines')
        if not rbac.is_space_manager_identity(request.user, makerspace_id):
            raise PermissionDenied()
        serializer = MachineTypeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slug = serializer.validated_data.get("slug")
        if MachineType.objects.filter(makerspace_id=makerspace_id, slug=slug).exists():
            raise ValidationError({"slug": "A machine type with this slug already exists."})
        machine_type = MachineType.objects.create(
            makerspace_id=makerspace_id,
            is_builtin=False,
            managing_action='',
            **serializer.validated_data,
        )
        audit.record(
            request.user,
            'machine_type.created',
            makerspace=machine_type.makerspace,
            target=machine_type,
            target_type='machine_type',
        )
        return Response(
            MachineTypeSerializer(machine_type).data,
            status=status.HTTP_201_CREATED,
        )


class MachineTypeDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin machines'],
        summary='Update a custom machine type',
        request=MachineTypeUpdateSerializer,
        responses={
            200: MachineTypeSerializer,
            400: OpenApiResponse(description='Invalid or built-in machine type.'),
            403: OpenApiResponse(description='Machine management permission required.'),
            404: OpenApiResponse(description='Machine type not found.'),
        },
    )
    def patch(self, request, makerspace_id, pk, *args, **kwargs):
        require_module(makerspace_id, 'machines')
        if not rbac.is_space_manager_identity(request.user, makerspace_id):
            raise PermissionDenied()
        machine_type = get_object_or_404(
            MachineType.objects.filter(
                Q(makerspace_id=makerspace_id) | Q(makerspace__isnull=True)
            ),
            pk=pk,
        )
        if machine_type.is_builtin or machine_type.makerspace_id is None:
            raise ValidationError('Built-in machine types cannot be changed.')

        serializer = MachineTypeUpdateSerializer(
            machine_type,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                machine_type = serializer.save()
                audit.record(
                    request.user,
                    'machine_type.updated',
                    makerspace=machine_type.makerspace,
                    target=machine_type,
                    target_type='machine_type',
                )
        except IntegrityError:
            raise ValidationError(
                'A machine type with this name or slug already exists in this makerspace.'
            )
        return Response(MachineTypeSerializer(machine_type).data)
