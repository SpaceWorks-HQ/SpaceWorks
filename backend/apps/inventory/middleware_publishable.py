"""Publishable browser keys authorize a public site independently of its catalogue."""

import logging
from urllib.parse import urlsplit

from apps.inventory.middleware_observability import (
    UNKNOWN_CLIENT, ORIGIN_DENIED, set_failure_reason,
)

logger = logging.getLogger("apps.inventory.middleware")


class PublishableKeyMixin:
    def _publishable_key_is_valid(self, request):
        key = request.headers.get("X-Publishable-Key") or request.GET.get("key")
        if not key:
            return False
        try:
            from apps.makerspaces.models import Makerspace

            makerspace = Makerspace.objects.filter(
                public_api_key=key,
                public_site_enabled=True,
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

