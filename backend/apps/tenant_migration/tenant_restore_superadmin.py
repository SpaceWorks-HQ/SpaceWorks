"""Create exactly one provenance-bound target operator for Lane D."""

import hashlib
import secrets
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.audit import services as audit
from apps.backup.models import DeploymentRecoveryState

from .tenant_restore_types import TenantRestoreRefused


def superadmin_provenance(*, run_id, artifact_sha256, email):
    normalized = email.strip().lower()
    raw = f"lane-d-superadmin-v1\0{artifact_sha256}\0{run_id}\0{normalized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_target_superadmin(
    *, email, run_id, artifact_sha256, delivery_store, using="default"
):
    email = (email or "").strip().lower()
    try:
        validate_email(email)
        run_uuid = uuid.UUID(str(run_id))
    except (ValidationError, ValueError, TypeError) as exc:
        raise TenantRestoreRefused("The target superadmin email or run ID is invalid.") from exc
    provenance = superadmin_provenance(
        run_id=run_uuid, artifact_sha256=artifact_sha256, email=email
    )
    username = f"lane_d_admin_{run_uuid.hex}"
    User = get_user_model()
    existing_named = User.objects.using(using).filter(username=username).first()
    email_owners = User.objects.using(using).filter(email__iexact=email)
    if existing_named is not None:
        email_owners = email_owners.exclude(pk=existing_named.pk)
    if email_owners.exists():
        raise TenantRestoreRefused(
            "The target superadmin email belongs to an imported user or stub."
        )
    delivery = delivery_store.get_or_prepare(
        provenance=provenance,
        kind="target_superadmin",
        target=email,
        secret_factory=lambda: secrets.token_urlsafe(48),
    )
    password = delivery["secret"]
    with transaction.atomic(using=using):
        email_owner = (
            User.objects.using(using).select_for_update().filter(email__iexact=email).first()
        )
        existing = (
            User.objects.using(using).select_for_update().filter(username=username).first()
        )
        if email_owner is not None and email_owner.pk != getattr(existing, "pk", None):
            # This deliberately covers imported full rows and any malformed/imported
            # stub that still carries an address. The operator principal never adopts it.
            raise TenantRestoreRefused(
                "The target superadmin email belongs to an imported user or stub."
            )
        if existing is not None:
            if (
                existing.email.lower() != email
                or not existing.is_superuser
                or not existing.is_staff
                or existing.role != User.Role.SUPERADMIN
                or not existing.check_password(password)
            ):
                raise TenantRestoreRefused("Target superadmin provenance conflicts.")
            return existing
        user = User(
            username=username,
            email=email,
            is_superuser=True,
            is_staff=True,
            is_active=True,
            role=User.Role.SUPERADMIN,
            access_status=User.AccessStatus.ACTIVE,
            must_change_password=True,
        )
        user.set_password(password)
        user.full_clean()
        user.save(using=using)
        state, _ = DeploymentRecoveryState.objects.using(using).select_for_update().get_or_create(
            pk=1, defaults={"mode": DeploymentRecoveryState.Mode.TARGET_IMPORT}
        )
        if state.mode != DeploymentRecoveryState.Mode.TARGET_IMPORT:
            raise TenantRestoreRefused("Target superadmin can be created only in target-import mode.")
        state.recovery_principal = user
        state.save(using=using, update_fields=("recovery_principal", "updated_at"))
        audit.record(
            user,
            "tenant_migration.target_superadmin_created",
            target=user,
            meta={"provenance": provenance, "host_supplied_email": True},
        )
    return user
