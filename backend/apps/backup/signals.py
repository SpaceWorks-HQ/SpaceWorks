from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.backup import recovery_cache
from apps.backup.models import DeploymentRecoveryState


@receiver(post_save, sender=DeploymentRecoveryState)
def _invalidate_recovery_mode_cache(sender, instance, **kwargs):
    """Drop the cached mode whenever the row is written, by any path.

    On commit rather than immediately: an uncommitted mode is not yet true for anyone else,
    and invalidating early would let a concurrent request re-cache the OLD value read from
    its own snapshot, leaving the stale entry in place for the full TTL after the change
    lands. `on_commit` runs immediately when no transaction is active.
    """
    transaction.on_commit(recovery_cache.invalidate)
