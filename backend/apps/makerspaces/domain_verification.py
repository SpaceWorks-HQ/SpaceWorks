import dns.resolver
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.makerspaces.hosting import canonical_host
from apps.makerspaces.models import Makerspace

EXPECTED_HOST_PREFIX = "_spaceworks-verify"
LEGACY_EXPECTED_HOST_PREFIX = "_osmm-verify"
EXPECTED_HOST_PREFIXES = (EXPECTED_HOST_PREFIX, LEGACY_EXPECTED_HOST_PREFIX)
DOMAIN_CHANGE_COOLDOWN_MESSAGE = (
    "You changed your domain recently; please wait before changing it again."
)


def is_self_host() -> bool:
    """Self-host mode = no platform suffix configured. In that mode the operator
    controls both DNS and the server, so a custom domain is trusted (by a
    superadmin) without the TXT challenge that defends the shared managed box."""
    return not str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip()


def expected_record(makerspace):
    if is_self_host() or not makerspace.frontend_domain:
        return None
    return {
        "host": f"{EXPECTED_HOST_PREFIX}.{makerspace.frontend_domain}",
        "type": "TXT",
        "value": makerspace.domain_verification_token,
    }


def _resolve_txt(name):
    resolver = dns.resolver.Resolver()
    resolver.timeout = 5
    resolver.lifetime = 5
    answers = resolver.resolve(name, "TXT")
    return [
        b"".join(part for part in answer.strings).decode("utf-8")
        for answer in answers
    ]


def resolves_to_origin(makerspace) -> bool:
    configured_origin = str(settings.PLATFORM_ORIGIN_HOST or "").strip()
    if not configured_origin:
        return True

    domain = canonical_host(makerspace.frontend_domain or "")
    origin = canonical_host(configured_origin)
    if domain is None or origin is None:
        return False

    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 5
        try:
            cname_answers = resolver.resolve(domain, "CNAME")
        except dns.resolver.NoAnswer:
            cname_answers = ()
        if any(
            canonical_host(str(answer.target)) == origin
            for answer in cname_answers
        ):
            return True

        domain_addresses = {str(answer) for answer in resolver.resolve(domain, "A")}
        origin_addresses = {str(answer) for answer in resolver.resolve(origin, "A")}
        return bool(domain_addresses & origin_addresses)
    except Exception:
        return False


def domain_change_cooldown_active(makerspace, normalized_domain) -> bool:
    cooldown_seconds = settings.DOMAIN_CHANGE_COOLDOWN_SECONDS
    return bool(
        cooldown_seconds > 0
        and makerspace is not None
        and normalized_domain != makerspace.frontend_domain
        and makerspace.frontend_domain_changed_at is not None
        and (timezone.now() - makerspace.frontend_domain_changed_at).total_seconds()
        < cooldown_seconds
    )


def apply_domain_change(makerspace, frontend_domain) -> None:
    """The one status transition for a changed ``frontend_domain`` (unsaved).

    VERIFIED is the trust gate for CORS, staff origins, Host validation and on-demand
    TLS, so a new host must never inherit the old host's VERIFIED. Self-host trusts a
    superadmin-set domain at once; managed hosting sends it back to PENDING until the TXT
    challenge passes. Every writer -- the staff serializer and the /control/ form --
    calls this rather than restating it; the caller owns the authority check.
    """
    now = timezone.now()
    makerspace.frontend_domain_changed_at = now
    if is_self_host() and frontend_domain:
        makerspace.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
        makerspace.domain_verified_at = now
    else:
        makerspace.frontend_domain_status = Makerspace.DomainStatus.PENDING
        makerspace.domain_verified_at = None


def _is_platform_managed(domain) -> bool:
    suffix = str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip().lower()
    canonical = canonical_host(domain or "")
    if not suffix or not canonical:
        return False
    return canonical == suffix.lstrip(".") or canonical.endswith(suffix)


def _commit_status(makerspace, target, status, *, set_verified_at, detail):
    """Persist a verification outcome, but re-read the row under a lock first so a
    concurrent domain change can never have this (slow, DNS-based) result written
    onto a different — and unverified — hostname. The status gates host admission
    and on-demand TLS, so a stale write would trust an unchecked domain."""
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if locked.frontend_domain != target:
            makerspace.frontend_domain_status = locked.frontend_domain_status
            makerspace.domain_verified_at = locked.domain_verified_at
            return (
                locked.frontend_domain_status,
                locked.domain_verified_at,
                "Domain changed during verification; please re-run.",
            )
        locked.frontend_domain_status = status
        fields = ["frontend_domain_status", "updated_at"]
        if set_verified_at:
            locked.domain_verified_at = timezone.now()
            fields.insert(1, "domain_verified_at")
        locked.save(update_fields=fields)
        makerspace.frontend_domain_status = locked.frontend_domain_status
        makerspace.domain_verified_at = locked.domain_verified_at
        return (locked.frontend_domain_status, locked.domain_verified_at, detail)


def verify_domain(makerspace):
    if not makerspace.frontend_domain:
        makerspace.frontend_domain_status = Makerspace.DomainStatus.PENDING
        makerspace.domain_verified_at = None
        makerspace.save(
            update_fields=[
                "frontend_domain_status",
                "domain_verified_at",
                "updated_at",
            ]
        )
        return (Makerspace.DomainStatus.PENDING, None, "No custom domain set.")

    target = makerspace.frontend_domain
    # Self-host: the operator owns DNS and the server, so a superadmin-set custom
    # domain is trusted immediately — the TXT challenge only defends the shared box.
    if is_self_host():
        return _commit_status(
            makerspace,
            target,
            Makerspace.DomainStatus.VERIFIED,
            set_verified_at=True,
            detail="Self-hosted custom domain — trusted automatically.",
        )
    # Platform subdomains are provisioned+verified by staff and have no per-tenant TXT
    # record. Running the custom-domain DNS flow on them would mark them FAILED and drop
    # the live tenant host from the allowlists — so keep them VERIFIED without a lookup.
    if _is_platform_managed(target):
        return _commit_status(
            makerspace,
            target,
            Makerspace.DomainStatus.VERIFIED,
            set_verified_at=True,
            detail="Platform-managed subdomain — verified automatically.",
        )

    records = []
    lookup_errors = []
    for prefix in EXPECTED_HOST_PREFIXES:
        try:
            records.extend(_resolve_txt(f"{prefix}.{target}"))
        except Exception as exc:  # A legacy DNS label may be absent during transition.
            lookup_errors.append(exc)

    if not records and lookup_errors:
        return _commit_status(
            makerspace,
            target,
            Makerspace.DomainStatus.FAILED,
            set_verified_at=False,
            detail=f"DNS lookup failed: {lookup_errors[0]}",
        )

    if makerspace.domain_verification_token in records:
        if not resolves_to_origin(makerspace):
            return _commit_status(
                makerspace,
                target,
                Makerspace.DomainStatus.FAILED,
                set_verified_at=False,
                detail="Domain does not resolve to the platform origin yet.",
            )
        return _commit_status(
            makerspace,
            target,
            Makerspace.DomainStatus.VERIFIED,
            set_verified_at=True,
            detail="Domain verified.",
        )

    return _commit_status(
        makerspace,
        target,
        Makerspace.DomainStatus.FAILED,
        set_verified_at=False,
        detail="Verification token was not found in DNS TXT records.",
    )
