import json
import uuid
from types import SimpleNamespace

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotAuthenticated, Throttled, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.audit_events import fingerprint
from apps.apiclients.throttling import ClientTierRateThrottle, MemberPrincipalRateThrottle
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.request_workflow import (
    RequesterSnapshot,
    anonymous_idempotency_replay,
)
from apps.hardware_requests.serializers import (
    PublicRequestStatusSerializer,
    RequestSubmitResponseSerializer,
    RequestSubmitSerializer,
)
from apps.hardware_requests.throttles import (
    AnonymousRequestEmailThrottle,
    AnonymousRequestIpBurstThrottle,
    AnonymousRequestIpHourThrottle,
)
from apps.hardware_requests.view_helpers import (
    ERROR_404,
    PUBLIC_ERROR_RESPONSES,
    request_queryset,
)
from apps.inventory.models import InventoryProduct
from apps.makerspaces.anonymous_requesters import get_or_create_anonymous_requester
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset
from apps.presence.guard import require_active_account, require_active_member_presence
from apps.openapi import (
    PUBLIC_API_AUTH_PARAMETERS,
    PUBLIC_REQUEST_STATUS_EXAMPLE,
    PUBLIC_REQUEST_SUBMIT_EXAMPLE,
)


class RequestSubmitView(APIView):
    permission_classes = [AllowAny]
    # Anonymous throttles are selected inside post(). The authenticated throttle stays
    # in APIView.initial() through check_throttles(), preserving the original ordering.
    throttle_classes = []
    throttle_scope = "public_request_submit"

    def check_throttles(self, request):
        if request.user.is_authenticated:
            _enforce_throttles(request, self, (MemberPrincipalRateThrottle,))

    @extend_schema(
        tags=["Public requests"],
        summary="Submit public borrow request",
        auth=[{"jwtAuth": []}, {}],
        parameters=[
            *PUBLIC_API_AUTH_PARAMETERS,
            OpenApiParameter(
                name="Idempotency-Key",
                type=str,
                location=OpenApiParameter.HEADER,
                required=False,
                description=(
                    "Required for account-less submissions. Reusing a key with the same "
                    "payload returns the original request; a different payload is rejected."
                ),
            ),
        ],
        request=RequestSubmitSerializer,
        responses={201: RequestSubmitResponseSerializer, **PUBLIC_ERROR_RESPONSES},
        examples=[PUBLIC_REQUEST_SUBMIT_EXAMPLE],
    )
    def post(self, request, makerspace_slug, *args, **kwargs):
        makerspace = get_public_makerspace(makerspace_slug)
        anonymous_submission = not request.user.is_authenticated
        if anonymous_submission:
            if not makerspace.anonymous_requests_enabled:
                # Raising DRF's own exception preserves the previous IsAuthenticated
                # response body as well as its 401 status for every non-opted-in space.
                raise NotAuthenticated()
            # Resolving the opt-in flag is unavoidable because disabled spaces must
            # retain their 401. From here the raw honeypot precedes module checks,
            # throttling, serializer work, product queries and principal creation.
            if _honeypot_filled(request.data):
                return _honeypot_response()
            _require_module(makerspace, "request_workflow")
            _enforce_throttles(
                request,
                self,
                (AnonymousRequestIpBurstThrottle, AnonymousRequestIpHourThrottle),
            )
        else:
            _require_module(makerspace, "request_workflow")
            if module_enabled(makerspace, "membership"):
                require_active_member_presence(request.user, makerspace)
            else:
                # Waiver acceptance lives on MakerspaceMembership and cannot be recorded
                # with membership off. In this configuration the flow is public request ->
                # STAFF ACCEPT, and staff acceptance is the proposal-time control.
                require_active_account(request.user, makerspace)
            if _honeypot_filled(request.data):
                return _honeypot_response()

        serializer = RequestSubmitSerializer(
            data=request.data,
            context={"anonymous_submission": anonymous_submission},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data.pop("website", None)

        idempotency_key_fingerprint = ""
        payload_fingerprint = ""
        if anonymous_submission:
            request.anonymous_contact_email = data["contact_email"]
            _enforce_throttles(request, self, (AnonymousRequestEmailThrottle,))
            idempotency_key = str(request.headers.get("Idempotency-Key", "")).strip()
            if not idempotency_key:
                raise ValidationError(
                    {"idempotency_key": "This header is required for anonymous submissions."}
                )
            if len(idempotency_key) > settings.ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH:
                raise ValidationError(
                    {
                        "idempotency_key": (
                            "Ensure this header has no more than "
                            f"{settings.ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH} characters."
                        )
                    }
                )
            idempotency_key_fingerprint = fingerprint(idempotency_key)
            payload_fingerprint = _anonymous_payload_fingerprint(data)
            replay = anonymous_idempotency_replay(
                makerspace,
                idempotency_key_fingerprint,
                payload_fingerprint,
            )
            if replay is not None:
                return Response(
                    RequestSubmitResponseSerializer(replay).data,
                    status=status.HTTP_201_CREATED,
                )

        product_ids = [item["product_id"] for item in data["items"]]
        products = _requestable_products(product_ids, makerspace)
        if len(products) != len(product_ids):
            raise ValidationError(
                {"items": "One or more products are unavailable for request."}
            )

        if anonymous_submission:
            requester_principal = get_or_create_anonymous_requester(makerspace)
            contact_snapshot = RequesterSnapshot(
                username="",
                name=data["contact_name"].strip(),
                email=data["contact_email"],
                phone=data.get("contact_phone", ""),
                contact_verified=False,
            )
            audit_actor = None
        else:
            requester_principal = request.user
            contact_snapshot = RequesterSnapshot(
                username=request.user.username,
                name=request.user.display_name,
                email=request.user.email,
                phone=request.user.phone,
                contact_verified=True,
            )
            audit_actor = request.user

        hardware_request = workflow.submit_request(
            makerspace,
            [
                {
                    "product": products[item["product_id"]],
                    "quantity": item["quantity"],
                }
                for item in data["items"]
            ],
            data["requested_for"],
            requester_principal=requester_principal,
            contact_snapshot=contact_snapshot,
            audit_actor=audit_actor,
            idempotency_key_fingerprint=idempotency_key_fingerprint,
            payload_fingerprint=payload_fingerprint,
        )
        return Response(
            RequestSubmitResponseSerializer(hardware_request).data,
            status=status.HTTP_201_CREATED,
        )


def _honeypot_response():
    decoy = SimpleNamespace(
        public_token=uuid.uuid4(),
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    return Response(
        RequestSubmitResponseSerializer(decoy).data,
        status=status.HTTP_201_CREATED,
    )


def _enforce_throttles(request, view, throttle_types):
    waits = []
    for throttle_type in throttle_types:
        throttle = throttle_type()
        if not throttle.allow_request(request, view):
            waits.append(throttle.wait())
    if waits:
        durations = [wait for wait in waits if wait is not None]
        raise Throttled(wait=max(durations) if durations else None)


def _anonymous_payload_fingerprint(data):
    canonical = {
        "contact_email": data["contact_email"],
        "contact_name": data["contact_name"].strip(),
        "contact_phone": data.get("contact_phone", ""),
        "items": sorted(data["items"], key=lambda item: item["product_id"]),
        "requested_for": data["requested_for"],
    }
    return fingerprint(json.dumps(canonical, sort_keys=True, separators=(",", ":")))


class RequestStatusView(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "request_status"
    serializer_class = PublicRequestStatusSerializer
    lookup_field = "public_token"

    def get_queryset(self):
        from apps.hardware_requests.view_helpers import request_queryset

        return servable_queryset(request_queryset(), relation="makerspace")

    @extend_schema(
        tags=["Public requests"],
        summary="Get request status by public token",
        auth=[],
        parameters=PUBLIC_API_AUTH_PARAMETERS,
        responses={200: PublicRequestStatusSerializer, 404: ERROR_404},
        examples=[PUBLIC_REQUEST_STATUS_EXAMPLE],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


def _honeypot_filled(payload):
    """True if the hidden anti-spam `website` field was populated. Real browsers never
    fill it; bots that auto-fill every field do. Read defensively from the raw payload."""
    try:
        value = payload.get("website", "")
    except AttributeError:
        return False
    return bool(str(value).strip())


def _requestable_products(product_ids, makerspace):
    return {
        product.pk: product
        for product in InventoryProduct.objects.filter(
            pk__in=product_ids,
            makerspace=makerspace,
            is_public=True,
            is_archived=False,
        )
    }


def _require_module(makerspace, module_key):
    if not module_enabled(makerspace, module_key):
        raise ValidationError({"module": f"{module_key} is disabled for this makerspace."})
