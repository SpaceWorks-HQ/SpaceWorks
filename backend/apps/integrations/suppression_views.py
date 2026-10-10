from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.integrations.delivery_serializers import SuppressionPageSerializer, SuppressionSerializer, SuppressionWriteSerializer
from apps.integrations.delivery_views import staff_space
from apps.integrations.email_preferences import address_hash
from apps.integrations.models_suppression import EmailSuppression
from apps.openapi_errors import errors


def rows(user, space):
    return rbac.scope_by_action(user, rbac.Action.MANAGE_MAKERSPACE,
                               EmailSuppression.objects.all()).filter(makerspace=space)


class SuppressionListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Notification delivery"], responses={200: SuppressionPageSerializer, **errors(401, 403, 404)})
    def get(self, request, makerspace_id):
        space = staff_space(request.user, makerspace_id)
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows(request.user, space).order_by("-created_at", "-pk"), request, view=self)
        return paginator.get_paginated_response(SuppressionSerializer(page, many=True).data)

    @extend_schema(tags=["Notification delivery"], request=SuppressionWriteSerializer,
                   responses={201: SuppressionSerializer, **errors(400, 401, 403, 404, 423, 503)})
    def post(self, request, makerspace_id):
        space = staff_space(request.user, makerspace_id)
        serializer = SuppressionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            row, _ = rows(request.user, space).update_or_create(
                makerspace=space, address_hash=address_hash(space.pk, data["address"]),
                defaults={"reason": data["reason"], "created_by": request.user},
            )
            audit.record(request.user, "email.suppressed", makerspace=space, target=space,
                         meta={"reason": data["reason"]})
        return Response(SuppressionSerializer(row).data, status=201)


class SuppressionDeleteView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Notification delivery"], responses={
        204: OpenApiResponse(description="Suppression removed after operator review."), **errors(401, 403, 404, 423, 503),
    })
    def delete(self, request, makerspace_id, pk):
        space = staff_space(request.user, makerspace_id)
        with transaction.atomic():
            row = get_object_or_404(rows(request.user, space), pk=pk)
            row.delete()
            audit.record(request.user, "email.unsuppressed", makerspace=space, target=space)
        return Response(status=204)
