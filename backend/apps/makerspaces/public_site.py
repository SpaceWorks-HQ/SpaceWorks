"""Public catalogue gate: tenant publication and loan capability both apply."""

from django.http import Http404

from apps.makerspaces.guards import require_feature, require_module_for_servable


def require_public_catalogue(makerspace):
    # A private catalogue must have the same response as an unknown tenant,
    # even when its module or feature is also disabled.
    if not makerspace.public_site_enabled or not makerspace.public_inventory_enabled:
        raise Http404
    require_module_for_servable(makerspace, "public_inventory")
    require_feature(makerspace, "loans.enabled")
