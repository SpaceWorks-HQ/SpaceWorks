import hmac

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest
from apps.integrations.serializers import (
    TelegramTestAlertSerializer,
    TelegramWebhookSerializer,
)
from apps.integrations.telegram import TelegramDeliveryError, send_message
from apps.makerspaces.models import Makerspace
from apps.makerspaces.guards import require_module
from apps.tenant_migration.gate_runtime import tenant_write


class TelegramWebhookView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "telegram_webhook"

    @extend_schema(
        tags=["Telegram"],
        summary="Receive Telegram callback webhook",
        auth=[],
        request=TelegramWebhookSerializer,
        responses={200: OpenApiResponse(description="Webhook processed.")},
    )
    def post(self, request, *args, **kwargs):
        if not _webhook_secret_ok(request):
            return Response({"detail": "Invalid webhook secret."}, status=403)
        serializer = TelegramWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        callback = serializer.validated_data.get("callback_query")
        if not callback:
            return Response({"detail": "Ignored."})

        actor = _telegram_actor(callback)
        action, request_id, reason = _parse_callback(callback.get("data", ""))
        hardware_request = get_object_or_404(HardwareRequest, pk=request_id)
        with tenant_write(hardware_request.makerspace_id):
            require_module(hardware_request.makerspace, "telegram")
            if action == "accept":
                if not rbac.can(actor, rbac.Action.ACCEPT_REQUEST, hardware_request.makerspace_id):
                    return Response({"detail": "Permission denied."}, status=403)
                workflow.accept_request(actor, hardware_request)
            elif action == "reject":
                if not rbac.can(actor, rbac.Action.REJECT_REQUEST, hardware_request.makerspace_id):
                    return Response({"detail": "Permission denied."}, status=403)
                workflow.reject_request(actor, hardware_request, reason or "Rejected from Telegram.")
            else:
                return Response({"detail": "Unsupported action."}, status=400)
        return Response({"detail": "Processed."})


class TelegramTestAlertView(APIView):
    @extend_schema(
        tags=["Telegram"],
        summary="Send Telegram test alert",
        request=TelegramTestAlertSerializer,
        responses={200: OpenApiResponse(description="Delivery attempt result.")},
    )
    def post(self, request, *args, **kwargs):
        serializer = TelegramTestAlertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        makerspace = get_object_or_404(
            Makerspace,
            pk=serializer.validated_data["makerspace_id"],
        )
        require_module(makerspace, "telegram")
        from rest_framework.exceptions import PermissionDenied

        # rbac.can checks membership/action only; gate access_status too so a
        # suspended/restricted staffer with a live JWT can't still send alerts.
        if request.user.access_status != User.AccessStatus.ACTIVE:
            raise PermissionDenied()
        if not rbac.can(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id):
            raise PermissionDenied()
        # send_message returns False only when the makerspace has no token/chat_id
        # configured; a real Telegram failure (bad token, bot not in the group,
        # network) RAISES TelegramDeliveryError. Catch it here so the staff console
        # gets a clear {delivered:false, detail} instead of an opaque 500 — the test
        # alert is a diagnostic, so a delivery failure is an expected outcome, not a
        # server error.
        try:
            delivered = send_message(makerspace, serializer.validated_data["message"])
        except TelegramDeliveryError:
            return Response(
                {
                    "delivered": False,
                    "detail": (
                        "Telegram rejected the message. Check the bot token is correct "
                        "and the bot has been added to the group chat."
                    ),
                }
            )
        if not delivered:
            return Response(
                {
                    "delivered": False,
                    "detail": "Telegram is not configured — save a bot token and group chat ID first.",
                }
            )
        return Response({"delivered": True})


def _webhook_secret_ok(request):
    # Telegram echoes the secret_token configured at setWebhook time in this header.
    # Fail closed when unset: `from.id` in the payload is attacker-controllable, so
    # without this the accept/reject workflow could be driven by anyone.
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    if not secret:
        return False
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return hmac.compare_digest(provided, secret)


def _telegram_actor(callback):
    from rest_framework.exceptions import PermissionDenied

    telegram_id = str((callback.get("from") or {}).get("id") or "")
    # Guard the empty id: filtering on "" would match every user with a blank
    # telegram_user_id. Also require active standing so a suspended/restricted or
    # deactivated staffer can't drive accept/reject from an old inline button.
    if not telegram_id:
        raise PermissionDenied("Telegram actor is not linked to a staff user.")
    actor = User.objects.filter(
        telegram_user_id=telegram_id,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    ).first()
    if not actor:
        raise PermissionDenied("Telegram actor is not linked to an active staff user.")
    return actor


def _parse_callback(data):
    parts = str(data).split(":", 2)
    if len(parts) < 2:
        return None, None, ""
    action = parts[0]
    try:
        request_id = int(parts[1])
    except ValueError:
        request_id = None
    reason = parts[2] if len(parts) > 2 else ""
    return action, request_id, reason
