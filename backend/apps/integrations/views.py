import hmac
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.integrations.serializers import (
    TelegramTestAlertSerializer,
    TelegramWebhookSerializer,
)
from apps.integrations.telegram import TelegramDeliveryError, send_message
from apps.makerspaces.models import Makerspace
from apps.makerspaces.guards import require_module

logger = logging.getLogger(__name__)


class TelegramWebhookView(APIView):
    """Accept-and-ignore. Telegram is a notification channel, not an action surface.

    The accept/reject buttons are gone and this endpoint no longer touches the request
    workflow. **The route is kept anyway**, deliberately: a deployment that has already
    called `setWebhook` has this URL registered with Telegram, we cannot call
    `deleteWebhook` on its behalf, and Telegram retries a non-2xx response for hours. A
    200 acknowledgement is the graceful retirement; a 404 would be a permanent error loop
    in someone else's infrastructure.

    The secret check stays for the same reason it was added -- `from.id` in the payload is
    attacker-controllable and the endpoint must stay closed to strangers -- and because
    the moment a callback DID something again, an endpoint that had quietly stopped
    checking would be the vulnerability.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "telegram_webhook"

    @extend_schema(
        tags=["Telegram"],
        summary="Acknowledge a Telegram webhook (no action is taken)",
        description=(
            "Retained so an already-registered webhook does not retry forever. Callback "
            "queries are acknowledged and discarded: accepting and rejecting borrow "
            "requests happens in the staff console, never from chat."
        ),
        auth=[],
        request=TelegramWebhookSerializer,
        responses={200: OpenApiResponse(description="Acknowledged; no action taken.")},
    )
    def post(self, request, *args, **kwargs):
        if not _webhook_secret_ok(request):
            return Response({"detail": "Invalid webhook secret."}, status=403)
        serializer = TelegramWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("callback_query"):
            logger.info(
                "Telegram callback ignored; chat is not an action surface.",
                extra={"has_callback": True},
            )
        return Response({"detail": "Ignored."})


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
    # Fail closed when unset. Nothing behind this endpoint acts any more, but `from.id`
    # in the payload is attacker-controllable, and an endpoint that quietly stopped
    # authenticating is exactly what would turn a future callback into a vulnerability.
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    if not secret:
        return False
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return hmac.compare_digest(provided, secret)
