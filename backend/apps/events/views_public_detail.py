from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.events.serializers_public import PublicEventSerializer
from apps.events.views_public import _public_events, PUBLIC_EVENT_ERRORS
from apps.makerspaces.guards import require_module_for_servable
from apps.makerspaces.lookup import get_public_makerspace


class PublicEventDetailView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(tags=["Public events"], auth=[], request=None, responses={200: PublicEventSerializer, **PUBLIC_EVENT_ERRORS})
    def get(self, request, makerspace_slug, public_token):
        space = get_public_makerspace(makerspace_slug)
        require_module_for_servable(space, "events")
        event = get_object_or_404(_public_events(space).select_related("makerspace__payment_settings", "series", "category"), public_token=public_token)
        return Response(PublicEventSerializer(event, context={"request": request}).data)
