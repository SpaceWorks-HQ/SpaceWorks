"""Self-booking identity with optional community waiver obligations."""

from apps.makerspaces.models import MakerspaceMembership
from apps.presence.guard import require_active_account, require_active_member


def require_booking_account(user, makerspace):
    active = require_active_account(user, makerspace)
    # A membership is optional, but an existing revoked membership or outstanding
    # waiver must not be bypassed by the account-only branch.
    if MakerspaceMembership.objects.filter(user=user, makerspace=makerspace).exists():
        return require_active_member(user, makerspace)
    return active
