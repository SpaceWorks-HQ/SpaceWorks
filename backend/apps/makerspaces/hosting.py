import re

from django.conf import settings
from django.core.cache import cache

from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


CACHE_KEY = "hosting:verified_domains"
_DNS_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def canonical_host(raw: str) -> str | None:
    candidate = (raw or "").strip().lower()
    if not candidate or candidate.startswith("[") or candidate.count(":") > 1:
        return None
    if ":" in candidate:
        candidate, port = candidate.rsplit(":", 1)
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return None
    candidate = candidate.rstrip(".")
    if not candidate or len(candidate) > 253:
        return None
    labels = candidate.split(".")
    if labels[-1].isdigit() or any(not _DNS_LABEL.fullmatch(label) for label in labels):
        return None
    return candidate


def _without_port(host: str) -> str:
    candidate = str(host).strip().lower().rstrip(".")
    if candidate.count(":") == 1:
        name, port = candidate.rsplit(":", 1)
        if port.isdigit():
            return name.rstrip(".")
    return candidate


def is_infra_host(host: str) -> bool:
    candidate = str(host).strip().lower().rstrip(".")
    candidate_without_port = _without_port(candidate)
    for configured in settings.INFRA_HOSTS:
        configured_host = str(configured).strip().lower().rstrip(".")
        if candidate == configured_host:
            return True
        if candidate_without_port == _without_port(configured_host):
            return True
    return False


def verified_frontend_domains() -> frozenset[str]:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return frozenset(cached)
    domains = frozenset(
        domain.lower()
        for domain in servable_queryset(Makerspace.objects.filter(
            frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
            frontend_domain__isnull=False,
        ))
        .exclude(frontend_domain="")
        .values_list("frontend_domain", flat=True)
    )
    cache.set(CACHE_KEY, domains)
    return domains


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def host_is_allowed(host: str) -> bool:
    try:
        if is_infra_host(host):
            return True
        candidate = canonical_host(host)
        if candidate is None:
            return False
        return is_infra_host(candidate) or candidate in verified_frontend_domains()
    except Exception:
        return False
