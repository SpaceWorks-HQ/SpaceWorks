"""Member-editable identity fields and revocable browser/native sessions."""

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import audit_events
from apps.accounts.models import User
from apps.accounts.models_devices import DeviceGrant
from apps.accounts.serializers_self_service import (
    AccountProfileSerializer, AccountSessionPageSerializer,
)
from apps.accounts.services_tokens import revoke_device_grant
from apps.accounts.web_sessions import active_sessions, legacy_sessions, revoke_session, revoke_legacy_session
from apps.audit import services as audit
from apps.accounts.schemas_self_service import ACCOUNT_ERRORS as ERRORS
from apps.makerspaces.self_service_access import own_membership
from apps.makerspaces.guards import require_feature_locked



class AccountProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Member account"], request=None,
                   responses={200: AccountProfileSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        own_membership(request.user, makerspace_id)
        return Response(AccountProfileSerializer(request.user).data)

    @extend_schema(tags=["Member account"], request=AccountProfileSerializer,
                   responses={200: AccountProfileSerializer, **ERRORS})
    def patch(self, request, makerspace_id):
        own_membership(request.user, makerspace_id)
        with transaction.atomic():
            require_feature_locked(makerspace_id, "membership.self_service")
            membership = own_membership(request.user, makerspace_id)
            user = User.objects.select_for_update().get(pk=request.user.pk)
            serializer = AccountProfileSerializer(user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            # Store field names, not contact values, in the permanent audit trail.
            audit.record(user, "account.profile_updated", makerspace=membership.makerspace,
                         target=user, meta={"fields": sorted(serializer.validated_data)})
        return Response(serializer.data)


class AccountSessionListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Member account"], request=None,
                   responses={200: AccountSessionPageSerializer, **ERRORS})
    def get(self, request, makerspace_id):
        own_membership(request.user, makerspace_id)
        token = request.auth or {}
        rows = [{
            "id": f"web:{row.jti.removeprefix('session:')}", "kind": "web",
            "created_at": row.created_at, "expires_at": row.expires_at,
            "last_used_at": None, "current": row.jti == token.get("sid"),
        } for row in active_sessions(request.user)]
        rows.extend({
            "id": f"web-legacy:{row.jti}", "kind": "web",
            "created_at": row.created_at, "expires_at": row.expires_at,
            "last_used_at": None, "current": False,
        } for row in legacy_sessions(request.user))
        rows.extend({
            "id": f"device:{row.pk}", "kind": "device", "created_at": row.created_at,
            "expires_at": None, "last_used_at": row.last_used_at,
            "current": str(row.pk) == str(token.get("device_grant_id") or ""),
        } for row in DeviceGrant.objects.filter(user=request.user, status=DeviceGrant.Status.ACTIVE,
                                               registration__status="approved"))
        rows.sort(key=lambda row: row["created_at"] or timezone.now(), reverse=True)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


class AccountSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Member account"], request=None, responses={204: None, **ERRORS})
    def delete(self, request, makerspace_id, session_id):
        own_membership(request.user, makerspace_id)
        kind, separator, identifier = session_id.partition(":")
        if not separator:
            raise NotFound("Session not found.")
        with transaction.atomic():
            require_feature_locked(makerspace_id, "membership.self_service")
            membership = own_membership(request.user, makerspace_id)
            if kind == "web":
                row = revoke_session(request.user, f"session:{identifier}")
            elif kind == "web-legacy":
                row = revoke_legacy_session(request.user, identifier)
            elif kind == "device":
                import uuid
                try:
                    grant_id = uuid.UUID(identifier)
                except ValueError as exc:
                    raise NotFound("Session not found.") from exc
                row = DeviceGrant.objects.select_for_update().filter(pk=grant_id, user=request.user).first()
                if row is None:
                    raise NotFound("Session not found.")
                revoke_device_grant(row)
            else:
                raise NotFound("Session not found.")
            audit.record(request.user, "account.session_revoked", makerspace=membership.makerspace,
                         target=request.user, meta={"kind": kind,
                                                  "session_hash": audit_events.fingerprint(row.pk)})
        return Response(status=204)
