"""Superadmin-only per-module data purge (plan A9).

This is NOT `lifecycle.purge()`. That deletes an entire archived makerspace; this
deletes one module's rows while the makerspace stays live and every other module
keeps working.

The contract that makes it safe to offer at all:

* **Uninstall first.** A module must already be uninstalled (tombstoned) before its
  data can be purged. Uninstall is reversible and retains everything; purge is the
  separate, explicit, irreversible second step. Requiring the order means no single
  command can both hide and destroy.
* **Superadmin only**, mirroring `lifecycle.purge()`.
* **One transaction**, with immutability triggers bypassed for DELETE only, exactly
  as the makerspace purge does -- `session_replication_role='replica'` on self-host,
  the `app.allow_immutable_delete` GUC on managed Postgres where the replication role
  is forbidden. Both are `SET LOCAL`, so a crash can never leave the append-only
  guards durably disabled.
* **Object storage last.** Keys are collected before the delete and removed after the
  commit, best-effort: a failed S3 call must not roll back a completed purge.
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.audit import services as audit
from apps.makerspaces.module_purge_plans import BY_KEY, NOT_SEPARABLE, PLANS
from apps.makerspaces.module_registry import BY_KEY as MODULE_BY_KEY

logger = logging.getLogger(__name__)


def purgeable_modules():
    """Plans in registry order, for `list_modules` and the console."""
    return [{"key": plan.key, "summary": plan.summary} for plan in PLANS]


def purge_module(makerspace, key, actor):
    """Delete one module's data for one makerspace. Returns the row counts."""
    plan = _resolve(makerspace, key, actor)

    meta = {
        "makerspace_id": makerspace.pk,
        "slug": makerspace.slug,
        "module": plan.key,
    }
    audit.record(actor, "makerspace.module_purge_started", makerspace=None, target=None, meta=meta)

    with transaction.atomic():
        locked = makerspace.__class__.objects.select_for_update().get(pk=makerspace.pk)
        # Re-check under the lock: an install could have committed since `_resolve`.
        if plan.key in (locked.enabled_modules or []):
            raise ValidationError(
                f"{plan.key} was re-installed; uninstall it again before purging."
            )
        # Collect under the makerspace lock to narrow the attach/delete race. This does
        # not eliminate it under READ COMMITTED: a row another transaction commits
        # between this SELECT and the DELETE is invisible to the former and visible to
        # the latter, and attach paths take this lock only in managed mode because
        # `limits.add_storage` returns early on self-host.
        private_keys = _collect_private_keys(locked, plan)
        private_sizes = _collect_private_key_sizes(locked, plan)
        public_keys = _collect_public_keys(locked, plan)
        with connection.cursor() as cursor:
            if settings.MANAGED_POSTGRES:
                cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
            else:
                cursor.execute("SET LOCAL session_replication_role = 'replica'")
            counts = _purge(locked, plan, cursor)

    audit.record(
        actor,
        "makerspace.module_purged",
        makerspace=None,
        target=None,
        meta={**meta, "counts": counts},
    )
    # Both accounting paths run after commit and release quota only for objects the
    # bucket confirmed are gone -- a failed delete must free nothing, or the makerspace
    # stops being charged for storage it still holds.
    _free_private_storage(makerspace, private_sizes, _delete_private_keys(private_keys))
    # Storage HEADs cannot run inside the purge transaction: network failures must not
    # roll back deleted rows or hold the makerspace lock across one round trip per key.
    _delete_public_images_and_free_storage(makerspace, public_keys)
    return counts


def _resolve(makerspace, key, actor):
    if not getattr(actor, "is_superuser", False):
        raise ValidationError("Only a superuser can purge module data.")
    plan = BY_KEY.get(key)
    if plan is None:
        reason = NOT_SEPARABLE.get(key)
        if reason:
            raise ValidationError(f"{key} cannot be purged on its own. {reason}")
        if key in MODULE_BY_KEY:
            raise ValidationError(f"{key} stores no data of its own, so there is nothing to purge.")
        raise ValidationError(f"Unknown module {key!r}.")
    if key in (makerspace.enabled_modules or []):
        raise ValidationError(
            f"{key} is still installed. Uninstall it first -- purging is a separate, "
            "irreversible step."
        )
    return plan


def _purge(makerspace, plan, cursor):
    counts = {}
    # Payments are deliberately NOT deleted here, by any plan. Switching a module off and
    # then purging its rows is not a reason to destroy the financial record of money that
    # really changed hands -- a receipt must stay visible and a pending charge payable. They
    # do become generic-keyed references to a vanished subject, which is why `Payment`
    # snapshots `subject_label` at creation and `clean()` tolerates a missing subject on an
    # otherwise-unchanged row. The whole-makerspace `lifecycle.purge` still deletes them:
    # `Payment.makerspace` is PROTECT, so they cannot outlive their makerspace.
    # Blind-index rows have no FK to their source row, so nothing else deletes them.
    # They hold keyed HMACs of PII: leaving them behind is a real leak, not untidiness.
    if plan.pii_labels:
        from apps.encryption.models import PiiBlindIndex

        deleted = PiiBlindIndex.objects.filter(
            makerspace=makerspace, model_label__in=plan.pii_labels
        ).delete()[0]
        if deleted:
            counts["pii_blind_index"] = deleted
    counts.update(plan.delete(makerspace, cursor))
    return counts


def _collect_private_keys(makerspace, plan):
    from apps.backup.models import RestoreRollbackObject

    keys, seen = [], set()

    def add(key):
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    if plan.private_keys is not None:
        plan.private_keys(makerspace, add)
    for key in RestoreRollbackObject.objects.filter(
        makerspace=makerspace,
        module_key=plan.key,
        bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE,
    ).exclude(copy_key="").values_list("copy_key", flat=True):
        add(key)
    return keys


def _collect_public_keys(makerspace, plan):
    from apps.backup.models import RestoreRollbackObject

    keys = list(plan.public_image_keys(makerspace)) if plan.public_image_keys is not None else []
    keys.extend(
        RestoreRollbackObject.objects.filter(
            makerspace=makerspace,
            module_key=plan.key,
            bucket_kind=RestoreRollbackObject.BucketKind.PUBLIC_IMAGE,
        ).exclude(copy_key="").values_list("copy_key", flat=True)
    )
    return [key for key in dict.fromkeys(keys) if key]


def _delete_private_keys(keys):
    """Best-effort delete of private objects; returns the keys the bucket confirmed gone.

    The return value is what lets the caller release storage quota for those keys only.
    A client that cannot even be constructed confirms nothing, so nothing is freed.
    """
    if not keys:
        return set()
    from apps.evidence import storage

    try:
        client = storage._client()
    except Exception:
        logger.exception("module_purge_storage_client_failed", extra={"keys": len(keys)})
        return set()
    deleted = set()
    for key in keys:
        try:
            client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
        except Exception:
            logger.exception("module_purge_storage_delete_failed: %s", key)
        else:
            deleted.add(key)
    if deleted:
        from apps.backup.models import RestoreRollbackObject

        RestoreRollbackObject.objects.filter(copy_key__in=deleted).delete()
    return deleted


def _collect_private_key_sizes(makerspace, plan):
    from apps.backup.models import RestoreRollbackObject

    sizes = plan.private_key_sizes(makerspace) if plan.private_key_sizes is not None else {}
    sizes.update({
        key: size for key, size in RestoreRollbackObject.objects.filter(
            makerspace=makerspace,
            module_key=plan.key,
            bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE,
        ).exclude(copy_key="").values_list("copy_key", "size_bytes")
    })
    return sizes


def _free_private_storage(makerspace, sizes, deleted_keys):
    """Release charged bytes for private objects that were confirmed deleted."""
    if not sizes or not deleted_keys:
        return
    freed = sum(
        size for key, size in sizes.items() if size and key in deleted_keys
    )
    if not freed:
        return
    from apps.makerspaces import limits

    try:
        limits.free_storage(makerspace, freed)
    except Exception:
        logger.exception("module_purge_private_accounting_failed", extra={"bytes": freed})


def _delete_public_images_and_free_storage(makerspace, keys):
    if not keys:
        return
    from apps.inventory import public_image_storage

    # Freeing first when a best-effort delete silently failed makes the counter
    # permanently wrong in the direction that grants free storage.
    for key in keys:
        public_image_storage.release_public_image(makerspace, key)
        from apps.backup.models import RestoreRollbackObject

        RestoreRollbackObject.objects.filter(copy_key=key).delete()
