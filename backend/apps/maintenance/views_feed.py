import hashlib

from django.http import HttpResponse
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.accounts import rbac
from apps.apiclients.throttling import MemberPrincipalRateThrottle, ClientTierRateThrottle
from apps.hardware_requests.exceptions import ErrorSerializer
from .calendar_feed import feed_space, issue, revoke, resolve, render
from .models_feed import MaintenanceCalendarFeed

ERRORS = {code: ErrorSerializer for code in (401, 403, 404, 423, 429, 503)}
ERRORS[400] = {"type": "object", "additionalProperties": True}


class FeedStateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    token_hint = serializers.CharField(allow_null=True)


class FeedIssuedSerializer(serializers.Serializer):
    feed_url = serializers.URLField()
    token_hint = serializers.CharField()


class EmptySerializer(serializers.Serializer):
    def validate(self, attrs):
        if self.initial_data:
            raise serializers.ValidationError("No fields are accepted.")
        return attrs


class MaintenanceFeedView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [MemberPrincipalRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(request=None, responses={200: FeedStateSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        space = feed_space(request.user, makerspace_id)
        row = rbac.scope_verified_tenant(MaintenanceCalendarFeed.objects.all(), space).filter(user=request.user, revoked_at__isnull=True).first()
        return Response({"enabled": bool(row), "token_hint": row.token_hint if row else None})

    @extend_schema(request=EmptySerializer, responses={200: FeedIssuedSerializer, **ERRORS})
    def post(self, request, makerspace_id):
        serializer = EmptySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row, token = issue(request.user, feed_space(request.user, makerspace_id))
        path = reverse("maintenance-feed-calendar", kwargs={"makerspace_id": makerspace_id, "raw_token": token})
        return Response({"feed_url": request.build_absolute_uri(path), "token_hint": row.token_hint})

    @extend_schema(request=None, responses={204: None, **ERRORS})
    def delete(self, request, makerspace_id):
        revoke(request.user, feed_space(request.user, makerspace_id))
        return Response(status=204)


class MaintenanceFeedCalendarView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(auth=[], request=None, responses={(200, "text/calendar"): OpenApiTypes.BINARY, 304: None, **ERRORS})
    def get(self, request, makerspace_id, raw_token):
        row = resolve(makerspace_id, raw_token)
        if row is None:
            raise NotFound()
        try:
            space = feed_space(row.user, makerspace_id)
        except PermissionDenied as exc:
            raise NotFound() from exc
        payload = render(row.user, space)
        etag = '"'+hashlib.sha256(payload).hexdigest()+'"'
        response = HttpResponse(status=304) if request.headers.get("If-None-Match") == etag else HttpResponse(payload, content_type="text/calendar; charset=utf-8")
        response["ETag"] = etag
        response["Cache-Control"] = "private, no-store"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Robots-Tag"] = "noindex"
        return response
