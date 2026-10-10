"""The one lock order every device mutation takes: Makerspace -> Device -> Enrollment.

``lock_tenant`` is called first inside the mutation's ``transaction.atomic()``. It
holds the tenant source-gate lock, takes the same Makerspace row lock that
``module_install`` uninstall/purge take (so a disable and a device write serialize with
unambiguous winners), and re-checks canonical servability under that lock because
``module_enabled`` deliberately answers capability for an archived tenant.
"""

from rest_framework.exceptions import PermissionDenied

from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.servability import is_servable
from apps.tenant_migration.gate_runtime import assert_write_allowed

MODULE_KEY = "devices"


def lock_tenant(makerspace_id):
    assert_write_allowed(makerspace_id)
    makerspace = require_module_locked(makerspace_id, MODULE_KEY)
    if not is_servable(makerspace):
        raise PermissionDenied("This makerspace is not available.")
    return makerspace
