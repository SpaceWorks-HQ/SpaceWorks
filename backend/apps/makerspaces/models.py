from urllib.parse import urlsplit

from django.utils.crypto import get_random_string

from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.module_registry import default_enabled_module_keys
from apps.makerspaces.validators import DEFAULT_PRESENCE_PRESETS


def generate_publishable_key():
    return f"pk_{get_random_string(32)}"


def generate_domain_verification_token():
    return f"dv_{get_random_string(48)}"


def generate_public_code():
    return get_random_string(4, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def normalize_frontend_domain(value):
    """Reduce a pasted domain/URL/origin to a bare lowercase host (or None).

    A staff member may paste `https://alpha.example/admin`; storing that raw would
    make the origin helpers build `https://https://alpha.example`. Extract just the
    host so `frontend_domain` is always a bare hostname.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return None
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "") or None


# Derived from the module registry -- kept as a module-level name because the
# /control/ form and several tests import it. Add a module in module_registry.py.
DEFAULT_ENABLED_MODULES = default_enabled_module_keys()


def default_enabled_modules():
    # Referenced by migration 0009 as a JSONField default, so this import path is
    # load-bearing and must keep resolving. Returns a fresh list every call.
    return default_enabled_module_keys()


def default_theme_config():
    return {
        "mode": "light",
        "primary_color": "#2563eb",
        "accent_color": "#16a34a",
        "logo_url": "",
    }


def default_branding_config():
    return {
        "display_name": "",
        "support_email": "",
        "support_url": "",
    }


def presence_presets(makerspace):
    """Configured presence lengths, with an empty configuration using the defaults."""
    return makerspace.presence_preset_minutes or list(DEFAULT_PRESENCE_PRESETS)


from apps.makerspaces.models_makerspace import Makerspace  # noqa: E402,F401
from apps.makerspaces.models_memberships import MakerspaceMembership  # noqa: E402,F401
from apps.makerspaces.models_roles import (  # noqa: E402,F401
    MakerspaceRole,
    MakerspaceWaiver,
    MembershipRequest,
    SubdomainRequest,
)
from apps.makerspaces.models_profiles import (  # noqa: E402,F401
    MemberProfile,
    MemberProject,
)
from apps.makerspaces.models_archive_requests import (  # noqa: E402,F401
    MakerspaceArchiveRequest,
)
from apps.makerspaces.models_imports import (  # noqa: E402,F401
    ImportedUserReconciliation,
    PendingImportedMembership,
)
