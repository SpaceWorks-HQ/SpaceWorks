import hashlib
import hmac
import logging
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from apps.apiclients import telemetry
from apps.apiclients.crypto import decrypt_secret
from apps.inventory.middleware_nonce import (
    NONCE_MAX_LENGTH,
    body_could_re_encode_nonce,
    claim_nonce,
    nonce_is_valid,
)
from apps.inventory.middleware_observability import (
    BAD_SIGNATURE,
    NONCE_MISSING,
    NONCE_REPLAY,
    NO_CREDENTIALS,
    ORIGIN_DENIED,
    SKEW,
    TARGET_UNRESOLVED,
    TENANT_MISMATCH,
    UNKNOWN_CLIENT,
    WOULD_REJECT_EVENT as WOULD_REJECT_EVENT,
    log_would_reject,
    scope_failure_reason,
    set_failure_reason,
)

logger = logging.getLogger(__name__)
LEGACY_NONCE_WARNING_EVENT = "api_client_nonce_missing_legacy"
AMBIGUOUS_NONCE_BODY_EVENT = "api_client_nonce_ambiguous_body"


class FrontendHMACMiddleware:
    """Validate signed client requests for protected API paths using the ApiClient registry."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_valid = True
        if self._is_protected_path(request):
            is_valid = self._is_valid(request)
            if not is_valid and not settings.API_CLIENT_AUTH_REQUIRED:
                log_would_reject(request)
        if self._should_reject_invalid(request) and not is_valid:
            return JsonResponse({"detail": "Invalid client signature."}, status=401)
        return self.get_response(request)

    def _should_reject_invalid(self, request):
        if request.method == "OPTIONS" or not self._is_protected_path(request):
            return False
        if settings.API_CLIENT_AUTH_REQUIRED:
            return True
        # Authentication remains optional during rollout, but credentials that opt in
        # to the nonce protocol must fail closed. Otherwise a replay would merely fall
        # through as anonymous while API_CLIENT_AUTH_REQUIRED is disabled.
        if request.headers.get("X-Nonce"):
            return True
        return settings.APICLIENT_REQUIRE_NONCE and self._has_hmac_credentials(request)

    def _has_hmac_credentials(self, request):
        return bool(
            request.headers.get("X-Timestamp")
            or request.headers.get("X-Signature")
            or request.headers.get("X-Nonce")
        )

    def _is_protected_path(self, request):
        return any(
            request.path.startswith(p) for p in settings.HMAC_PROTECTED_PATH_PREFIXES
        )

    def _is_valid(self, request):
        set_failure_reason(request, NO_CREDENTIALS)
        # X-Nonce selects the signed protocol. It must never be accepted through the
        # publishable-key or browser-client paths, where it would be replay decoration
        # rather than authenticated input.
        if not self._has_hmac_credentials(request):
            if self._publishable_key_is_valid(request):
                return True
            if self._frontend_client_is_valid(request):
                return True
        try:
            from apps.apiclients.models import ApiClient

            client_id = request.headers.get("X-Client-Id", "")
            timestamp = request.headers.get("X-Timestamp", "")
            signature = request.headers.get("X-Signature", "")
            nonce = request.headers.get("X-Nonce", "")
            if not (client_id and timestamp and signature):
                return False
            client = ApiClient.objects.filter(
                client_id=client_id, is_active=True
            ).first()
            if client is None:
                set_failure_reason(request, UNKNOWN_CLIENT)
                return False
            if not self._origin_ok(request, client):
                set_failure_reason(request, ORIGIN_DENIED)
                return False
            if not self._scope_checks_ok(request, client):
                return False
            try:
                skew = abs(int(time.time()) - int(timestamp))
            except ValueError:
                set_failure_reason(request, SKEW)
                return False
            if skew > settings.HMAC_MAX_CLOCK_SKEW_SECONDS:
                set_failure_reason(request, SKEW)
                return False

            if nonce:
                if not nonce_is_valid(nonce):
                    set_failure_reason(request, BAD_SIGNATURE)
                    return False
            elif settings.APICLIENT_REQUIRE_NONCE:
                set_failure_reason(request, NONCE_MISSING)
                return False
            elif body_could_re_encode_nonce(request.body):
                logger.warning(
                    AMBIGUOUS_NONCE_BODY_EVENT, extra={"client_id": client_id}
                )
                set_failure_reason(request, BAD_SIGNATURE)
                return False

            message_parts = [
                request.method.upper().encode(),
                request.get_full_path().encode(),
                timestamp.encode(),
            ]
            if nonce:
                message_parts.append(nonce.encode())
            message_parts.append(request.body)
            message = b"\n".join(message_parts)
            current_secret = client.get_secret()
            previous_secret_is_active = bool(
                client.previous_secret_encrypted and client.previous_secret_valid_until
                and client.previous_secret_valid_until > timezone.now()
            )
            previous_token = (
                client.previous_secret_encrypted if previous_secret_is_active
                else client.secret_encrypted
            )
            previous_secret = decrypt_secret(previous_token)
            current_expected = hmac.new(
                current_secret.encode(), message, hashlib.sha256
            ).hexdigest()
            previous_expected = hmac.new(
                previous_secret.encode(), message, hashlib.sha256
            ).hexdigest()
            current_matches = hmac.compare_digest(signature, current_expected)
            previous_matches = hmac.compare_digest(signature, previous_expected)
            if not (current_matches | previous_matches):
                set_failure_reason(request, BAD_SIGNATURE)
                return False
            if nonce:
                if not claim_nonce(client_id, nonce):
                    set_failure_reason(request, NONCE_REPLAY)
                    return False
            else:
                logger.warning(
                    LEGACY_NONCE_WARNING_EVENT,
                    extra={"client_id": client_id},
                )
            request.api_client = client
            telemetry.record_signed_client_observation(request, client)
            return True
        except Exception:  # fail safe - never 500 the request flow
            set_failure_reason(request, BAD_SIGNATURE)
            logger.exception("ApiClient signature validation failed")
            return False

    def _publishable_key_is_valid(self, request):
        key = request.headers.get("X-Publishable-Key") or request.GET.get("key")
        if not key:
            return False
        try:
            from apps.makerspaces.models import Makerspace

            makerspace = Makerspace.objects.filter(
                public_api_key=key,
                public_inventory_enabled=True,
            ).first()
            if makerspace is None:
                set_failure_reason(request, UNKNOWN_CLIENT)
                return False
            if not self._makerspace_scope_ok(request, makerspace):
                return False
            valid = self._publishable_origin_ok(request, makerspace)
            if not valid:
                set_failure_reason(request, ORIGIN_DENIED)
            return valid
        except Exception:
            logger.exception("Publishable key validation failed")
            return False

    def _publishable_origin_ok(self, request, makerspace):
        from apps.makerspaces.platform import makerspace_public_origins

        origins = makerspace_public_origins(makerspace)
        if not origins:
            return False
        raw = request.headers.get("Origin") or request.headers.get("Referer", "")
        if not raw:
            return False
        parts = urlsplit(raw)
        candidate = f"{parts.scheme}://{parts.netloc}" if parts.scheme else ""
        return candidate in origins

    def _origin_ok(self, request, client):
        raw = request.headers.get("Origin") or request.headers.get("Referer", "")
        if not raw:
            return client.client_type == "server"
        if not client.allowed_origins:
            return False
        parts = urlsplit(raw)
        candidate = f"{parts.scheme}://{parts.netloc}" if parts.scheme else ""
        return candidate in set(client.allowed_origins)

    def _frontend_client_is_valid(self, request):
        try:
            from apps.apiclients.models import ApiClient

            client_id = request.headers.get("X-Client-Id", "")
            timestamp = request.headers.get("X-Timestamp", "")
            signature = request.headers.get("X-Signature", "")
            if not client_id or timestamp or signature:
                return False
            client = ApiClient.objects.select_related("makerspace").filter(
                client_id=client_id,
                is_active=True,
            ).first()
            if client is None:
                set_failure_reason(request, UNKNOWN_CLIENT)
                return False
            # Browser identity is public config, so this path never grants a rate tier.
            if client.client_type != "browser" or not self._origin_ok(request, client):
                set_failure_reason(request, ORIGIN_DENIED)
                return False
            valid = self._scope_checks_ok(request, client)
            if valid:
                telemetry.record_browser_client_observation(request, client)
            return valid
        except Exception:
            logger.exception("Frontend ApiClient validation failed")
            return False

    def _client_scope_ok(self, request, client):
        from apps.apiclients import scope_registry

        entry = scope_registry.lookup(
            scope_registry.resolve_view_name(request), request.method
        )
        if entry is None:
            set_failure_reason(request, TARGET_UNRESOLVED)
            return False
        target, resolved = scope_registry.resolve_target_once(request, entry)
        allowed = scope_registry.target_allows(entry, client, target, resolved)
        if not allowed:
            reason = TARGET_UNRESOLVED if not resolved else TENANT_MISMATCH
            set_failure_reason(request, reason)
        return allowed

    def _makerspace_scope_ok(self, request, makerspace):
        from apps.apiclients import scope_registry

        entry = scope_registry.lookup(
            scope_registry.resolve_view_name(request), request.method
        )
        if entry is None:
            set_failure_reason(request, TARGET_UNRESOLVED)
            return False
        target, resolved = scope_registry.resolve_target_once(request, entry)
        if entry.target_mode == scope_registry.TARGET_GLOBAL:
            return True
        if not resolved:
            set_failure_reason(request, TARGET_UNRESOLVED)
            return False
        allowed = getattr(target, "pk", None) == makerspace.pk
        if not allowed:
            set_failure_reason(request, TENANT_MISMATCH)
        return allowed

    def _request_scope_ok(self, request, client):
        from apps.apiclients import scope_registry

        observation = scope_registry.classify(request, client)
        if not observation.verdict:
            set_failure_reason(request, scope_failure_reason(observation, client))
        return observation.verdict

    def _scope_checks_ok(self, request, client):
        request_scope_ok = self._request_scope_ok(request, client)
        return request_scope_ok and self._client_scope_ok(request, client)
