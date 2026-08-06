from urllib.parse import urlencode, urlparse

from django.conf import settings

from apps.inventory import public_image_storage
from apps.integrations.email import email_enabled
from apps.makerspaces.models import Makerspace, default_branding_config, default_theme_config
from apps.makerspaces.capabilities import FEATURE_MODULES, FEATURES
from apps.makerspaces.module_registry import is_frontend_exposed, module_workflows

# Derived from the module registry, which also decides frontend exposure: an
# internal master switch declares frontend_exposed=False and is dropped from both
# the bootstrap `modules` list and these workflows.
MODULE_WORKFLOWS = module_workflows()

FEATURE_WORKFLOWS = {
    "inventory.self_checkout": ["self_checkout", "self_return"],
}


def origin_to_hostname(origin):
    if not origin:
        return ""
    parsed = urlparse(origin if "://" in origin else f"//{origin}")
    return (parsed.hostname or "").lower()


def makerspace_staff_origins(makerspace):
    origins = set(settings.PLATFORM_STAFF_ORIGINS)
    if (
        makerspace.frontend_domain
        and makerspace.frontend_domain_status == Makerspace.DomainStatus.VERIFIED
    ):
        origins.add(f"https://{makerspace.frontend_domain}")
    return origins


def makerspace_public_origins(makerspace):
    return makerspace_staff_origins(makerspace) | set(makerspace.cors_allowed_origins or [])


def member_area_url(makerspace):
    """Return the canonical member-area URL for a makerspace frontend."""
    if (
        makerspace.frontend_domain
        and makerspace.frontend_domain_status == Makerspace.DomainStatus.VERIFIED
    ):
        return f"https://{makerspace.frontend_domain}/member"
    base = (settings.PUBLIC_APP_BASE_URL or "http://localhost:5000").rstrip("/")
    return f"{base}/m/{makerspace.slug}/member" if base and makerspace.slug else ""


def staff_payment_settings_url(makerspace=None, *, outcome):
    """Return a trusted staff settings URL without accepting browser input."""
    verified_domain = (
        makerspace is not None
        and makerspace.frontend_domain
        and makerspace.frontend_domain_status == Makerspace.DomainStatus.VERIFIED
    )
    if verified_domain:
        base = f"https://{makerspace.frontend_domain}"
    else:
        base = (settings.PUBLIC_APP_BASE_URL or "http://localhost:5000").rstrip("/")
    path = (
        "/admin/settings"
        if verified_domain
        else f"/m/{makerspace.slug}/admin/settings"
        if makerspace is not None and makerspace.slug
        else "/admin/settings"
    )
    return f"{base}{path}?{urlencode({'stripe_connect': outcome})}"


def resolve_frontend(*, tenant=None, slug=None, origin=None, host=None):
    if tenant:
        return Makerspace.objects.filter(
            public_code__iexact=tenant,
            archived_at__isnull=True,
        ).first()
    if slug:
        return Makerspace.objects.filter(
            slug=slug,
            archived_at__isnull=True,
        ).first()
    hostname = origin_to_hostname(origin) or origin_to_hostname(host)
    if hostname:
        return Makerspace.objects.filter(
            frontend_domain__iexact=hostname,
            archived_at__isnull=True,
        ).first()
    return None


def module_enabled(makerspace, module_key):
    return module_key in set(makerspace.enabled_modules or [])


def feature_enabled(makerspace, key):
    definition = FEATURES.get(key)
    if definition is None or key not in set(makerspace.enabled_features or []):
        return False
    # A string parent must be a recognised feature-module; None => standalone feature
    # with no parent-module prerequisite (e.g. self-checkout on a private makerspace).
    if definition.parent_module is not None and definition.parent_module not in FEATURE_MODULES:
        return False
    required_modules = [
        module
        for module in (definition.parent_module, *definition.requires_modules)
        if module is not None
    ]
    return all(
        module_enabled(makerspace, module) for module in required_modules
    ) and all(feature_enabled(makerspace, feature) for feature in definition.requires_features)

def bootstrap_payload(makerspace):
    modules = sorted(
        key for key in set(makerspace.enabled_modules or []) if is_frontend_exposed(key)
    )
    features = sorted(key for key, definition in FEATURES.items() if definition.frontend_exposed and feature_enabled(makerspace, key))
    theme = default_theme_config()
    theme.update(makerspace.theme_config or {})
    logo_url = public_image_storage.public_url(makerspace.logo_key) or theme.get("logo_url") or ""
    cover_image_url = public_image_storage.public_url(makerspace.cover_image_key) or ""
    branding = default_branding_config()
    branding.update(makerspace.branding_config or {})
    if not branding.get("display_name"):
        branding["display_name"] = makerspace.name
    workflows = sorted({
        workflow for module in modules for workflow in MODULE_WORKFLOWS.get(module, [])
    } | {
        workflow for feature in features for workflow in FEATURE_WORKFLOWS.get(feature, [])
    })
    makerspace_payload = {
        "id": makerspace.id,
        "name": makerspace.name,
        "slug": makerspace.slug,
        "public_code": makerspace.public_code,
        "location": makerspace.location,
        "map_url": makerspace.map_url,
        "logo_url": logo_url,
        "cover_image_url": cover_image_url,
        "public_stats_enabled": makerspace.public_stats_enabled,
        "membership_policy": makerspace.membership_policy,
    }
    # Advisory geofence: expose the flag ONLY when configured AND the feature is on, so
    # dormant/self-host bootstrap payloads stay byte-for-byte unchanged (self-host
    # invariant) and a disabled feature cannot leave the client asking for coordinates
    # the backend will ignore.
    if makerspace.geofence_effective and feature_enabled(makerspace, "presence.geofence"):
        makerspace_payload["geofence_enabled"] = True
    return {
        "makerspace": makerspace_payload,
        "frontend": {
            "type": "makerspace",
            "hostname": makerspace.frontend_domain or "",
            "allowed_origins": sorted(makerspace_public_origins(makerspace)),
        },
        "modules": modules,
        "features": features,
        "workflows": workflows,
        "theme": theme,
        "branding": branding,
        "email_enabled": email_enabled(),
        "public_api": {
            "base_url": "/api/v1",
            "publishable_key": makerspace.public_api_key,
            "inventory_path": f"/api/v1/public/{makerspace.slug}/inventory/",
        },
    }
