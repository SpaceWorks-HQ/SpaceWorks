from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.accounts import rbac
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module_for_servable
from apps.makerspaces.lookup import get_public_makerspace
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS
from .models import InventoryProduct
from .notify_me import subscribe, unsubscribe


class WatchResponseSerializer(serializers.Serializer):
    subscribed = serializers.BooleanField()


class WatchInputSerializer(serializers.Serializer):
    def validate(self, attrs):
        if self.initial_data:
            raise serializers.ValidationError("No contact details or other fields are accepted.")
        return attrs


ERRORS = {code: ErrorSerializer for code in (401, 403, 404, 423, 429, 503)}
ERRORS[400] = {"type": "object", "additionalProperties": True}


class PublicInventoryWatchView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_request_submit"

    def product(self, slug, pk):
        space = get_public_makerspace(slug)
        require_module_for_servable(space, "public_inventory")
        if not space.public_inventory_enabled:
            raise ValidationError({"detail": "Public inventory is disabled."})
        return get_object_or_404(rbac.scope_public_catalogue(
            InventoryProduct.objects.all(), space,
        ).filter(is_public=True, is_archived=False), pk=pk)

    @extend_schema(request=WatchInputSerializer, parameters=PUBLIC_API_AUTH_PARAMETERS, responses={200: WatchResponseSerializer, **ERRORS})
    def post(self, request, makerspace_slug, pk):
        serializer = WatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subscribe(self.product(makerspace_slug, pk), request.user)
        return Response({"subscribed": True})

    @extend_schema(request=None, parameters=PUBLIC_API_AUTH_PARAMETERS, responses={204: None, **ERRORS})
    def delete(self, request, makerspace_slug, pk):
        unsubscribe(self.product(makerspace_slug, pk), request.user)
        return Response(status=204)
