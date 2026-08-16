from urllib.parse import urlsplit

from corsheaders.signals import check_request_enabled
from django.conf import settings

from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import makerspace_public_origins, makerspace_staff_origins
from apps.makerspaces.servability import servable_queryset

_STAFF_PATH_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/admin/",
    "/api/v1/guest-admin/",
    "/api/v1/procurement/",
    "/api/v1/integrations/telegram/test-alert",
)


def _origin_host(origin):
    return (urlsplit(origin).hostname or "").lower()


def origin_is_registered(origin):
    if not origin:
        return False
    if origin in set(settings.PLATFORM_STAFF_ORIGINS):
        return True
    # Indexed lookup: a branded-domain origin matches by host; an API-client/public origin
    # matches by exact membership in cors_allowed_origins (jsonb containment).
    host = _origin_host(origin)
    if host:
        for makerspace in servable_queryset(Makerspace.objects.filter(
            frontend_domain__iexact=host,
            frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
        )):
            if origin in makerspace_public_origins(makerspace):
                return True
    return servable_queryset(Makerspace.objects.filter(
        cors_allowed_origins__contains=[origin],
    )).exists()


def staff_origin_is_registered(origin):
    """Credentialed staff-auth endpoints only trust the configured frontend domain."""
    if not origin:
        return False
    if origin in set(settings.PLATFORM_STAFF_ORIGINS):
        return True
    host = _origin_host(origin)
    if not host:
        return False
    # Narrow to the (at most one) makerspace owning this host, then require the EXACT
    # https://<frontend_domain> origin â€” never cors_allowed_origins.
    for makerspace in servable_queryset(Makerspace.objects.filter(
        frontend_domain__iexact=host,
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )):
        if origin in makerspace_staff_origins(makerspace):
            return True
    return False


def member_origin_is_registered(origin):
    """Trust first-party application origins, never public API-client origins."""
    if not origin:
        return False
    if origin in set(settings.CORS_ALLOWED_ORIGINS) | set(
        settings.PLATFORM_STAFF_ORIGINS
    ):
        return True
    host = _origin_host(origin)
    if not host:
        return False
    return any(
        origin in makerspace_staff_origins(makerspace)
        for makerspace in servable_queryset(Makerspace.objects.filter(
            frontend_domain__iexact=host,
            frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
        ))
    )


def _is_staff_path(path):
    if not path:
        return False
    for prefix in _STAFF_PATH_PREFIXES:
        if prefix == "/api/v1/integrations/telegram/test-alert":
            if path == prefix:
                return True
            continue
        if path == prefix or path.startswith(prefix):
            return True
    return False


def cors_allow_registered_frontend(sender, request, **kwargs):
    origin = request.headers.get("Origin")
    if _is_staff_path(request.path):
        return staff_origin_is_registered(origin)
    return origin_is_registered(origin)


def register_signal():
    check_request_enabled.connect(cors_allow_registered_frontend)
