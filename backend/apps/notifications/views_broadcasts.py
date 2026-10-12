from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.makerspaces.models import Makerspace
from apps.makerspaces.guards import require_module
from apps.makerspaces.platform import feature_enabled
from apps.notifications.access import personal_space
from apps.notifications.broadcasts import send_broadcast
from apps.notifications.models_inbox import NotificationInboxRow
from apps.notifications.serializers_inbox import InboxSerializer, InboxPageSerializer
from apps.notifications.serializers_broadcasts import BroadcastInputSerializer, BroadcastResultSerializer, BroadcastSerializer, BroadcastOptionsSerializer
from apps.openapi_errors import errors
from apps.tenant_migration.gate_runtime import tenant_write


def require_broadcasts(space):
    require_module(space, 'membership')
    require_module(space, 'notifications')
    if not feature_enabled(space, 'membership.broadcasts'):
        raise ValidationError({'feature': 'Member broadcasts are disabled.'})


class BroadcastCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=['Member communication'], responses={200: BroadcastOptionsSerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id):
        from apps.makerspaces.models import MembershipPlan
        from apps.makerspaces.platform import module_enabled
        space = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS,
                                                     Makerspace.objects.all(), field='pk'), pk=makerspace_id)
        require_broadcasts(space)
        plans = rbac.scope_notification_policy(MembershipPlan.objects.all(), makerspace_id=space.pk).order_by('name', 'pk').values('id', 'name')
        certifications = []
        if module_enabled(space, 'machines'):
            from apps.machines.models_certifications import CertificationType
            certifications = rbac.scope_notification_policy(CertificationType.objects.all(), makerspace_id=space.pk).filter(is_active=True).order_by('name', 'pk').values('id', 'name')
        return Response(BroadcastOptionsSerializer({'plans': list(plans), 'certifications': list(certifications)}).data)

    @extend_schema(tags=['Member communication'], request=BroadcastInputSerializer,
                   responses={201: BroadcastResultSerializer, **errors(400, 401, 403, 404, 423, 503)})
    def post(self, request, makerspace_id):
        space = get_object_or_404(rbac.scope_by_action(request.user, rbac.Action.MANAGE_MEMBERS,
                                                     Makerspace.objects.all(), field='pk'), pk=makerspace_id)
        require_broadcasts(space)
        serializer = BroadcastInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with tenant_write(space.pk):
            broadcast, count = send_broadcast(space, actor=request.user, **serializer.validated_data)
        return Response({'broadcast': BroadcastSerializer(broadcast).data, 'recipients': count}, status=201)


class AnnouncementFeedView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=['Member communication'], parameters=[OpenApiParameter('page', int)],
                   responses={200: InboxPageSerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id):
        space = personal_space(request.user, makerspace_id)
        require_broadcasts(space)
        rows = rbac.scope_personal_notifications(request.user, NotificationInboxRow.objects.all()).filter(
            makerspace=space, feature='members', event='broadcast',
        )
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(InboxSerializer(page, many=True).data)
