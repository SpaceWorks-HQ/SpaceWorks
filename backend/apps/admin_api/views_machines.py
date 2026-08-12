from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.machine_access import resolve_machine
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.machines import access
from apps.machines.models import Machine, MachineType
from apps.machines.serializers import MachineListResponseSerializer, MachineSerializer
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module, require_module_locked


class _MachinePagination(PageNumberPagination):
    # A page size comfortably above any realistic per-lab machine count, with an
    # opt-in ?page_size override and next/previous links so large fleets still page.
    page_size = 200
    page_size_query_param = 'page_size'
    max_page_size = 500


def _resolved_machine(user, pk):
    machine = resolve_machine(user, pk)
    require_module(machine.makerspace_id, 'machines')
    return machine


def _machine_types_for(makerspace_id):
    return MachineType.objects.filter(
        Q(makerspace__isnull=True) | Q(makerspace_id=makerspace_id)
    )


class MachineListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin machines'],
        summary='List machines in a makerspace',
        request=None,
        responses={200: MachineListResponseSerializer},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        require_module(makerspace_id, 'machines')
        if not access.can_see_machines(request.user, makerspace_id):
            raise PermissionDenied()
        queryset = access.scope_machines_for_actor(
            request.user,
            Machine.objects.select_related('makerspace', 'machine_type', 'warranty')
            .filter(makerspace_id=makerspace_id)
            .annotate(
                usage_total=Coalesce(
                    Sum('usage_entries__hours'),
                    Decimal('0'),
                )
            )
            # `Machine` declares no `Meta.ordering`, so this paginated list had no ORDER BY
            # at all: Postgres may return rows in any order per page, which lets a row
            # repeat on one page and vanish from another. `pk` is the tiebreaker -- ordering
            # by name alone is still unstable wherever two machines share one.
            .order_by('machine_type__name', 'name', 'pk'),
        )
        paginator = _MachinePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        capabilities = access.capabilities_for_machines(request.user, page)
        return Response(
            {
                'count': paginator.page.paginator.count,
                'next': paginator.get_next_link(),
                'previous': paginator.get_previous_link(),
                'results': MachineSerializer(
                    page,
                    many=True,
                    context={
                        'request': request,
                        'machine_capabilities': capabilities,
                    },
                ).data,
            }
        )

    @extend_schema(
        tags=['Admin machines'],
        summary='Create a machine',
        request=MachineSerializer,
        responses={
            201: MachineSerializer,
            400: OpenApiResponse(description='Invalid machine details.'),
        },
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = require_module(makerspace_id, 'machines')
        serializer = MachineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        machine_type = get_object_or_404(
            _machine_types_for(makerspace_id),
            pk=data['machine_type'].pk,
        )
        if not access.can_create_machine(request.user, makerspace_id, machine_type):
            raise PermissionDenied()
        with transaction.atomic():
            require_module_locked(makerspace, 'machines')
            limits.check_quota(makerspace, 'machines', adding=1)
            machine = Machine.objects.create(
                makerspace=makerspace,
                machine_type=machine_type,
                created_by=request.user,
                name=data['name'],
                location=data.get('location', ''),
                notes=data.get('notes', ''),
                firmware_version=data.get('firmware_version', ''),
                camera_feed_url=data.get('camera_feed_url', ''),
                type_payload=data.get('type_payload', {}),
            )
        audit.record(
            request.user,
            'machine.created',
            makerspace=machine.makerspace,
            target=machine,
            target_type='machine',
        )
        return Response(
            MachineSerializer(machine, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class MachineDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin machines'],
        summary='Retrieve a machine',
        request=None,
        responses={200: MachineSerializer},
    )
    def get(self, request, pk, *args, **kwargs):
        machine = _resolved_machine(request.user, pk)
        return Response(MachineSerializer(machine, context={'request': request}).data)

    @extend_schema(
        tags=['Admin machines'],
        summary='Update a machine',
        request=MachineSerializer,
        responses={
            200: MachineSerializer,
            400: OpenApiResponse(description='Invalid machine details.'),
        },
    )
    def patch(self, request, pk, *args, **kwargs):
        machine = _resolved_machine(request.user, pk)
        if not access.can_manage_machine(request.user, machine):
            raise PermissionDenied()
        serializer = MachineSerializer(machine, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # machine_type is immutable after creation: changing it could move a machine
        # to a type the actor is not authorized to manage (privilege escalation), so
        # it is never applied on update.
        serializer.validated_data.pop('machine_type', None)
        machine = serializer.save()
        audit.record(
            request.user,
            'machine.updated',
            makerspace=machine.makerspace,
            target=machine,
            target_type='machine',
        )
        return Response(
            MachineSerializer(machine, context={'request': request}).data
        )
