from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled, module_enabled


def require_module(makerspace_or_id, module_key):
    makerspace = (
        makerspace_or_id
        if isinstance(makerspace_or_id, Makerspace)
        else get_object_or_404(Makerspace, pk=makerspace_or_id)
    )
    if not module_enabled(makerspace, module_key):
        raise ValidationError({"module": f"{module_key} is disabled for this makerspace."})
    return makerspace


def require_module_locked(makerspace_or_id, module_key):
    """Re-check a module gate while holding the makerspace row lock (plan A8).

    `require_module` at the view boundary reads an unlocked row, so a concurrent
    uninstall can commit in the window between that check and the create -- leaving
    behind a row belonging to a module that is now off. Validating on the disable
    side instead does not help: it loses the same race from the other end.

    Every `module_install` mutation takes `select_for_update` on the makerspace, so
    taking the same lock here serializes creators against disablers, exactly the way
    `check_quota` serializes creators against each other. Call this **inside** the
    creation service's `transaction.atomic()`, next to the quota check, so both
    share one lock and one ordering.
    """
    pk = makerspace_or_id.pk if isinstance(makerspace_or_id, Makerspace) else makerspace_or_id
    locked = Makerspace.objects.select_for_update().get(pk=pk)
    if not module_enabled(locked, module_key):
        raise ValidationError({"module": f"{module_key} is disabled for this makerspace."})
    return locked


def require_feature(makerspace_or_id, feature_key):
    makerspace = (
        makerspace_or_id
        if isinstance(makerspace_or_id, Makerspace)
        else get_object_or_404(Makerspace, pk=makerspace_or_id)
    )
    if not feature_enabled(makerspace, feature_key):
        raise ValidationError({"feature": f"{feature_key} is disabled for this makerspace."})
    return makerspace


def require_feature_locked(makerspace_or_id, feature_key):
    """Re-check a feature gate while holding the makerspace row lock."""
    pk = makerspace_or_id.pk if isinstance(makerspace_or_id, Makerspace) else makerspace_or_id
    locked = Makerspace.objects.select_for_update().get(pk=pk)
    if not feature_enabled(locked, feature_key):
        raise ValidationError({"feature": f"{feature_key} is disabled for this makerspace."})
    return locked
