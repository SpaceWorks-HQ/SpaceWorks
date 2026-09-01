"""Staff lifecycle actions for machine-service requests."""

from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_service import (
    EmptyServiceActionSerializer,
    MachineServiceRequestSerializer,
    ServiceAcceptSerializer,
    ServiceCompleteSerializer,
    ServiceFailSerializer,
    ServiceRejectSerializer,
    ServiceStartSerializer,
)
from apps.admin_api.views_machine_service_common import (
    SERVICE_ERRORS,
    _manageable_request,
    _readable_or_collectable_request,
    _response,
)
from apps.machines import role_scope, service_workflow


class _MachineServiceActionView(APIView):
    permission_classes = [IsActiveStaff]
    input_serializer = EmptyServiceActionSerializer
    operation = None
    collect_partition = False

    def post(self, request, pk, *args, **kwargs):
        resolver = (
            _readable_or_collectable_request
            if self.collect_partition
            else _manageable_request
        )
        row = resolver(request.user, pk)
        serializer = self.input_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if self.operation == "accept":
            row = service_workflow.accept(row, request.user, **data)
        elif self.operation == "reject":
            row = service_workflow.reject(row, request.user, **data)
        elif self.operation == "start":
            machine_scope = role_scope.manage_scope_for(
                request.user, row.makerspace_id
            )
            row = service_workflow.start(row, request.user, machine_scope, **data)
        elif self.operation == "complete":
            row = service_workflow.complete(row, request.user, **data)
        elif self.operation == "fail":
            row = service_workflow.fail(row, request.user, **data)
        elif self.operation == "collect":
            row = service_workflow.collect(row, request.user)
        elif self.operation == "reprint":
            row = service_workflow.create_reprint(row, request.user)
        else:
            raise AssertionError("Unknown service action")
        return _response(row)


class MachineServiceAcceptView(_MachineServiceActionView):
    input_serializer, operation = ServiceAcceptSerializer, "accept"

    @extend_schema(tags=["Admin machine service"], summary="Accept a machine service request", request=ServiceAcceptSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)


class MachineServiceRejectView(_MachineServiceActionView):
    input_serializer, operation = ServiceRejectSerializer, "reject"

    @extend_schema(tags=["Admin machine service"], summary="Reject a machine service request", request=ServiceRejectSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)


class MachineServiceStartView(_MachineServiceActionView):
    input_serializer, operation = ServiceStartSerializer, "start"

    @extend_schema(tags=["Admin machine service"], summary="Start machine service work", request=ServiceStartSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)


class MachineServiceCompleteView(_MachineServiceActionView):
    input_serializer, operation = ServiceCompleteSerializer, "complete"

    @extend_schema(tags=["Admin machine service"], summary="Complete machine service work", request=ServiceCompleteSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)


class MachineServiceFailView(_MachineServiceActionView):
    input_serializer, operation = ServiceFailSerializer, "fail"

    @extend_schema(tags=["Admin machine service"], summary="Mark machine service work failed", request=ServiceFailSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)


class MachineServiceCollectView(_MachineServiceActionView):
    operation = "collect"
    collect_partition = True

    @extend_schema(tags=["Admin machine service"], summary="Mark a machine service request collected", request=EmptyServiceActionSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)


class MachineServiceReprintView(_MachineServiceActionView):
    operation = "reprint"

    @extend_schema(tags=["Admin machine service"], summary="Create a printer reprint", request=EmptyServiceActionSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)
