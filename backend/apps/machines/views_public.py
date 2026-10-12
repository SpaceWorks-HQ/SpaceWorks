from decimal import Decimal

from django.db.models import DecimalField, Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from apps.inventory.search import apply_q
from apps.makerspaces.editions import require_public_surface
from apps.apiclients.throttling import ClientTierRateThrottle
from apps.machines.models import Machine
from apps.machines.serializers_public_machines import PublicMachineSerializer
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.guards import require_module_for_servable
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


@extend_schema(
    tags=['Public machines'],
    summary='List public machines',
    description='List active machines published by a public makerspace.',
    parameters=[
        *PUBLIC_API_AUTH_PARAMETERS,
        OpenApiParameter(
            name='makerspace_slug',
            type=str,
            location=OpenApiParameter.PATH,
            description='Public makerspace code or slug.',
        ),
        OpenApiParameter(
            name='q', type=str, location=OpenApiParameter.QUERY, required=False,
            description='Full-text search over name, location, firmware version and notes; tolerates typos in the name.',
        ),
    ],
    responses={
        200: PublicMachineSerializer(many=True),
        400: OpenApiResponse(
            {"type": "object", "properties": {"module": {"type": "string"}},
             "required": ["module"]}, description="Machines module disabled.",
        ),
        404: OpenApiResponse(ErrorSerializer, description="Public makerspace not found."),
        401: OpenApiResponse(ErrorSerializer, description="Invalid API credentials."),
        403: OpenApiResponse(ErrorSerializer, description="API client not authorized."),
        429: OpenApiResponse(ErrorSerializer, description="Rate limit exceeded."),
    },
)
class PublicMachineListView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = 'public_read'
    serializer_class = PublicMachineSerializer

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs['makerspace_slug'])
        require_public_surface('machines')
        require_module_for_servable(makerspace, 'machines')
        if not makerspace.public_site_enabled:
            raise Http404
        queryset = (
            Machine.objects.select_related('machine_type')
            .filter(
                makerspace=makerspace,
                is_public=True,
                is_active=True,
            )
            .annotate(
                usage_total=Coalesce(
                    Sum('usage_entries__hours'),
                    Decimal('0'),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .order_by('name', 'id')
        )
        query = self.request.query_params.get('q', '')
        return apply_q(queryset, query) if query.strip() else queryset
