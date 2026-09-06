import hmac
import logging

from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import active_user
from apps.audit import services as audit
from apps.makerspaces.domain_verification import is_self_host
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
)
from apps.makerspaces.platform import staff_payment_settings_url
from apps.makerspaces.servability import is_servable
from apps.payments.connect import (
    account_has_pending_payments,
    deauthorize_account,
    exchange_oauth_code,
    fetch_account,
    oauth_state_is_latest,
    restrict_oauth_mapping,
    rollback_oauth_mapping,
    state_digest,
    update_account_status,
)
from apps.payments.models import (
    MakerspacePaymentSettings,
    PlatformStripeConnectSettings,
    StripeConnectOAuthState,
)
from apps.payments.services import apply_connect_webhook_event
from apps.payments.stripe_client import (
    PaymentsUnavailable,
    StripeWebhookSignatureError,
    construct_event,
)


logger = logging.getLogger(__name__)

class _PostExchangeRejected(Exception):
    pass


def _redirect(makerspace=None, outcome="failed"):
    response = HttpResponseRedirect(
        staff_payment_settings_url(makerspace, outcome=outcome)
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


def _lock_callback_authority(makerspace_id, actor_id):
    makerspace = Makerspace.objects.select_for_update().get(pk=makerspace_id)
    actor = User.objects.select_for_update().get(pk=actor_id)

    membership_snapshot = MakerspaceMembership.objects.filter(
        makerspace_id=makerspace_id,
        user_id=actor_id,
    ).values_list("assigned_role_id", flat=True).first()
    if membership_snapshot:
        MakerspaceRole.objects.select_for_update().get(pk=membership_snapshot)
    membership = (
        MakerspaceMembership.objects.select_for_update(of=("self",))
        .select_related("assigned_role")
        .filter(makerspace_id=makerspace_id, user_id=actor_id)
        .first()
    )
    if membership and membership.assigned_role_id != membership_snapshot:
        return makerspace, actor, False

    authorized = bool(
        is_servable(makerspace)
        and active_user(actor)
        and (
            (
                (actor.is_superuser or actor.role == User.Role.SUPERADMIN)
                and makerspace.superadmin_access_enabled
            )
            or rbac.Action.MANAGE_MAKERSPACE
            in rbac.actions_for_membership(membership)
        )
    )
    return makerspace, actor, authorized


class StripeConnectCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ["get", "options"]

    @extend_schema(
        tags=["Payments"],
        summary="Complete Stripe Connect onboarding",
        auth=[],
        parameters=[
            OpenApiParameter("state", str, OpenApiParameter.QUERY, required=True),
            OpenApiParameter("code", str, OpenApiParameter.QUERY),
            OpenApiParameter("error", str, OpenApiParameter.QUERY),
        ],
        responses={302: OpenApiResponse(description="Redirect to trusted staff settings.")},
    )
    def get(self, request):
        if is_self_host():
            raise Http404
        raw_state = request.query_params.get("state", "")
        digest = state_digest(raw_state)
        with transaction.atomic():
            oauth_state = (
                StripeConnectOAuthState.objects.select_for_update()
                .select_related("makerspace", "initiated_by")
                .filter(state_digest=digest)
                .first()
            )
            if not (
                oauth_state
                and hmac.compare_digest(oauth_state.state_digest, digest)
                and oauth_state.consumed_at is None
                and oauth_state.expires_at > timezone.now()
                and oauth_state_is_latest(oauth_state)
            ):
                return _redirect()
            oauth_state.consumed_at = timezone.now()
            oauth_state.save(update_fields=["consumed_at"])
            makerspace, actor = oauth_state.makerspace, oauth_state.initiated_by
            audit.record(
                actor,
                "payments.connect_callback_consumed",
                makerspace=makerspace,
                target=oauth_state,
            )
            if not (
                is_servable(makerspace)
                and active_user(actor)
                and rbac.can(
                    actor,
                    rbac.Action.MANAGE_MAKERSPACE,
                    makerspace.id,
                )
            ):
                return _redirect()

        if request.query_params.get("error") or not request.query_params.get("code"):
            return _redirect(makerspace)
        account_id = None
        mapping_persisted = False
        revoke_new_grant = False
        previous_mapping = {}
        try:
            account_id = exchange_oauth_code(request.query_params["code"])
            revoke_new_grant = not MakerspacePaymentSettings.objects.filter(
                connect_account_id=account_id
            ).exists()
            with transaction.atomic():
                makerspace, actor, authorized = _lock_callback_authority(
                    makerspace.id,
                    actor.id,
                )
                if not authorized or not oauth_state_is_latest(oauth_state):
                    raise _PostExchangeRejected
                merchant, _ = MakerspacePaymentSettings.objects.get_or_create(
                    makerspace=makerspace
                )
                if merchant.connect_account_id != account_id:
                    if merchant.connect_account_id and account_has_pending_payments(
                        merchant.connect_account_id
                    ):
                        raise _PostExchangeRejected
                    previous_mapping = {
                        "connect_account_id": merchant.connect_account_id,
                        "connect_account_assigned_at": merchant.connect_account_assigned_at,
                        "connect_status": merchant.connect_status,
                        "connect_charges_enabled": merchant.connect_charges_enabled,
                        "connect_payouts_enabled": merchant.connect_payouts_enabled,
                    }
                    merchant.connect_account_id = account_id
                    merchant.connect_account_assigned_at = timezone.now()
                    merchant.connect_status = MakerspacePaymentSettings.ConnectStatus.PENDING
                    merchant.connect_charges_enabled = False
                    merchant.connect_payouts_enabled = False
                    merchant.save(update_fields=list(previous_mapping))
                    audit.record(
                        actor,
                        "payments.connect_account_mapped",
                        makerspace=makerspace,
                        target=merchant,
                    )
            mapping_persisted = True
            account = fetch_account(account_id)
            with transaction.atomic():
                makerspace, actor, authorized = _lock_callback_authority(
                    makerspace.id, actor.id
                )
                if not authorized or not oauth_state_is_latest(oauth_state):
                    raise _PostExchangeRejected
                merchant = MakerspacePaymentSettings.objects.select_for_update().get(
                    makerspace=makerspace, connect_account_id=account_id
                )
                old_account_id = previous_mapping.get("connect_account_id")
                if old_account_id:
                    try:
                        deauthorize_account(old_account_id)
                    except Exception as exc:
                        raise _PostExchangeRejected from exc
                    audit.record(
                        actor,
                        "payments.connect_previous_authorization_revoked",
                        makerspace=makerspace,
                        target=merchant,
                        meta={"connect_account_id": old_account_id},
                    )
                merchant.connect_account_assigned_at = timezone.now()
                merchant.save(update_fields=["connect_account_assigned_at"])
                update_account_status(merchant, account)
                audit.record(
                    actor,
                    "payments.connect_onboarded",
                    makerspace=makerspace,
                    target=merchant,
                )
        except _PostExchangeRejected:
            if revoke_new_grant:
                rollback_oauth_mapping(
                    makerspace=makerspace,
                    actor=actor,
                    oauth_state=oauth_state,
                    account_id=account_id,
                    previous=previous_mapping,
                )
            return _redirect()
        except Exception:
            if account_id and not mapping_persisted and revoke_new_grant:
                try:
                    deauthorize_account(account_id)
                except Exception:
                    logger.exception("stripe_connect_orphan_revoke_failed")
            elif account_id and mapping_persisted:
                restrict_oauth_mapping(
                    makerspace=makerspace,
                    actor=actor,
                    oauth_state=oauth_state,
                    account_id=account_id,
                )
            return _redirect(makerspace)
        return _redirect(makerspace, "success")


class StripeConnectWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Payments"],
        summary="Receive a platform Stripe Connect webhook",
        auth=[],
        request=None,
        responses={
            200: OpenApiResponse(description="Verified event acknowledged."),
            400: OpenApiResponse(description="Invalid signature or configuration."),
            404: OpenApiResponse(description="Stripe Connect is dormant."),
        },
    )
    def post(self, request):
        if is_self_host():
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        platform = PlatformStripeConnectSettings.load()
        try:
            event = construct_event(
                request.body,
                request.headers.get("Stripe-Signature", ""),
                platform.get_stripe_webhook_secret(),
            )
        except (ImproperlyConfigured, InvalidToken):
            logger.warning("stripe_connect_webhook_configuration_unavailable")
            return Response(
                {"detail": "Invalid Stripe webhook signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (StripeWebhookSignatureError, PaymentsUnavailable, ValueError):
            logger.warning("stripe_connect_webhook_rejected")
            return Response(
                {"detail": "Invalid Stripe webhook signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        apply_connect_webhook_event(event)
        return Response({"detail": "Verified."})
