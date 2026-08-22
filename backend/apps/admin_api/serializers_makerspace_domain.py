import re

from django.conf import settings
from rest_framework import serializers

from apps.accounts.models import User
from apps.makerspaces import domain_verification, limits
from apps.makerspaces.hosting import canonical_host
from apps.makerspaces.models import Makerspace, normalize_frontend_domain


_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$"
)


def validate_frontend_domain(serializer, attrs):
    raw_domain = attrs.get("frontend_domain")
    normalized_domain = normalize_frontend_domain(raw_domain)
    attrs["frontend_domain"] = normalized_domain
    if normalized_domain is None and (raw_domain or "").strip():
        raise serializers.ValidationError(
            {"frontend_domain": "Enter a valid domain, e.g. alphamakerspace.com."}
        )
    if domain_verification.domain_change_cooldown_active(
        serializer.instance, normalized_domain
    ):
        raise serializers.ValidationError(
            {"frontend_domain": domain_verification.DOMAIN_CHANGE_COOLDOWN_MESSAGE}
        )
    if normalized_domain is None:
        return
    if not _HOSTNAME_RE.match(normalized_domain):
        raise serializers.ValidationError(
            {"frontend_domain": "Enter a valid domain, e.g. alphamakerspace.com."}
        )

    platform_suffix = str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip().lower()
    canonical = canonical_host(normalized_domain)
    current_domain = (
        serializer.instance.frontend_domain
        if serializer.instance is not None
        else None
    )
    domain_is_changing = normalized_domain != current_domain
    if domain_is_changing and domain_verification.is_self_host():
        actor = serializer.context["request"].user
        is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
        if not is_superadmin:
            raise serializers.ValidationError(
                {
                    "frontend_domain": (
                        "Only a superadmin can set the custom domain on a "
                        "self-hosted instance."
                    )
                }
            )
    platform_apex = platform_suffix.lstrip(".")
    if (
        platform_suffix
        and canonical
        and domain_is_changing
        and (canonical == platform_apex or canonical.endswith(platform_suffix))
    ):
        raise serializers.ValidationError(
            {
                "frontend_domain": (
                    "Platform subdomains are provisioned by staff, not set directly."
                )
            }
        )
    if (
        platform_suffix
        and domain_is_changing
        and not domain_verification.is_self_host()
    ):
        actor = serializer.context["request"].user
        is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
        override_ok = (
            serializer.instance is not None
            and limits.custom_domain_allowed(serializer.instance)
        )
        if not (is_superadmin or override_ok):
            raise serializers.ValidationError(
                {
                    "frontend_domain": (
                        "Custom domains aren't available on free managed hosting; "
                        "self-host to use your own domain."
                    )
                }
            )
    queryset = Makerspace.objects.filter(frontend_domain__iexact=normalized_domain)
    if serializer.instance is not None:
        queryset = queryset.exclude(pk=serializer.instance.pk)
    if queryset.exists():
        raise serializers.ValidationError(
            {
                "frontend_domain": (
                    "A makerspace with this frontend domain already exists."
                )
            }
        )
