from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.audit import services as audit
from apps.integrations.models_timing import NotificationTimingPolicy
from apps.integrations.serializers_timing import TimingPolicySerializer
from apps.makerspaces.models import Makerspace
from apps.makerspaces.guards import require_module
from apps.openapi_errors import errors
from apps.tenant_migration.gate_runtime import tenant_write


def policy_space(actor, makerspace_id):
    space = get_object_or_404(rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE,
                                                 Makerspace.objects.all(), makerspace_field='pk'), pk=makerspace_id)
    require_module(space, 'notifications')
    return space


def payload(policy):
    return {'quiet_start': policy.quiet_start, 'quiet_end': policy.quiet_end,
            'channels': policy.channels, 'digest_at': policy.digest_at,
            'bounce_configured': bool(policy.bounce_secret)}


class TimingPolicyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=['Notifications'], responses={200: TimingPolicySerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id):
        space = policy_space(request.user, makerspace_id)
        policy = rbac.scope_notification_policy(NotificationTimingPolicy.objects.all(), makerspace_id=space.pk).first()
        return Response(TimingPolicySerializer(payload(policy or NotificationTimingPolicy())).data)

    @extend_schema(tags=['Notifications'], request=TimingPolicySerializer,
                   responses={200: TimingPolicySerializer, **errors(400, 401, 403, 404, 423, 503)})
    def patch(self, request, makerspace_id):
        space = policy_space(request.user, makerspace_id)
        serializer = TimingPolicySerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with tenant_write(space.pk):
            policy_space(request.user, space.pk)
            from apps.makerspaces.guards import require_module_locked
            require_module_locked(space, 'notifications')
            policy, _ = rbac.scope_notification_policy(NotificationTimingPolicy.objects.all(), makerspace_id=space.pk).get_or_create(makerspace=space)
            policy = rbac.scope_notification_policy(NotificationTimingPolicy.objects.select_for_update(), makerspace_id=space.pk).get(pk=policy.pk)
            for name, value in serializer.validated_data.items():
                if name == 'bounce_secret':
                    policy.set_bounce_secret(value)
                else:
                    setattr(policy, name, value)
            policy.save()
            audit.record(request.user, 'notification.timing_updated', makerspace=space, target=policy,
                         meta={'fields': sorted(serializer.validated_data)})
        return Response(TimingPolicySerializer(payload(policy)).data)
