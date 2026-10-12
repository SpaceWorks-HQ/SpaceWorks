"""Device-route authorization. Never consults ``accounts.rbac``: a device holds no role."""

from rest_framework.permissions import BasePermission

from apps.devices import route_registry
from apps.devices.principal import DevicePrincipal
from apps.makerspaces.guards import require_module


class DeviceRoutePermission(BasePermission):
    """Default-deny: only an exact registered (route, method) is admitted."""

    def has_permission(self, request, view):
        entry = route_registry.entry_for(request)
        if entry is None:
            return False
        if entry.auth_mode == route_registry.ENROLLMENT_TOKEN:
            # The one-time token and proof of possession ARE the authentication; the
            # enrollment service verifies both under its locks.
            return True
        principal = request.user
        if not isinstance(principal, DevicePrincipal) or principal.kind not in entry.kinds:
            return False
        for module_key in entry.modules:
            require_module(principal.makerspace_id, module_key)
        return True
