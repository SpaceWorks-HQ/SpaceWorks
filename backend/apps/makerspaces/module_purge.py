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

    private_keys = _collect_private_keys(makerspace, plan)
    public_keys = _collect_public_keys(makerspace, plan)
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
    _delete_private_keys(private_keys)
    _delete_public_image_keys(public_keys)
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
    # Payments are immutable and reference their subject generically, so they must go
    # before the rows they point at or they survive as dangling references.
    if plan.payment_subjects:
        from apps.payments.models import Payment

        deleted = Payment.objects.filter(
            makerspace=makerspace, subject_type__in=plan.payment_subjects
        ).delete()[0]
        if deleted:
            counts["payments"] = deleted
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
    if plan.private_keys is None:
        return []
    keys, seen = [], set()

    def add(key):
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    plan.private_keys(makerspace, add)
    return keys


def _collect_public_keys(makerspace, plan):
    if plan.public_image_keys is None:
        return []
    return [key for key in dict.fromkeys(plan.public_image_keys(makerspace)) if key]


def _delete_private_keys(keys):
    if not keys:
        return
    from apps.evidence import storage

    try:
        client = storage._client()
    except Exception:
        logger.exception("module_purge_storage_client_failed", extra={"keys": len(keys)})
        return
    for key in keys:
        try:
            client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
        except Exception:
            logger.exception("module_purge_storage_delete_failed: %s", key)


def _delete_public_image_keys(keys):
    if not keys:
        return
    from apps.inventory import public_image_storage

    for key in keys:
        try:
            public_image_storage.delete_object(key)
        except Exception:
            logger.exception("module_purge_public_image_delete_failed: %s", key)
