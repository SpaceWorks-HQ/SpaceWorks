"""Target database identity, recovery gate and target-owned authority resets."""

from __future__ import annotations

from django.conf import settings
from django.db import connections, transaction

from apps.accounts.models_devices import NativeAppRegistration
from apps.backup.database_identity import (
    DatabaseIdentityError,
    establish_restored_database_identity,
    query_live_database_identity,
)
from apps.backup.models import DeploymentRecoveryState
from apps.backup.models_host_identity import DeploymentDatabaseIdentity

from .tenant_restore_types import TenantRestoreRefused


def establish_target_import_state(
    *, run_id, artifact_sha256, capture_id, using="default"
):
    with transaction.atomic(using=using):
        identity = (
            DeploymentDatabaseIdentity.objects.using(using)
            .select_for_update()
            .filter(pk=1)
            .first()
        )
        if identity is None:
            try:
                identity = establish_restored_database_identity(
                    run_id=run_id,
                    artifact_sha256=artifact_sha256,
                    capture_id=capture_id,
                    using=using,
                )
            except DatabaseIdentityError as exc:
                raise TenantRestoreRefused(
                    "Target database identity could not be established."
                ) from exc
        elif (
            str(identity.run_id),
            identity.artifact_sha256,
            str(identity.capture_id),
        ) != (str(run_id), artifact_sha256, str(capture_id)):
            raise TenantRestoreRefused(
                "Existing target database identity has different restore lineage."
            )
        state, _ = DeploymentRecoveryState.objects.using(using).select_for_update().get_or_create(
            pk=1,
            defaults={"mode": DeploymentRecoveryState.Mode.TARGET_IMPORT},
        )
        if state.mode not in {
            DeploymentRecoveryState.Mode.NORMAL,
            DeploymentRecoveryState.Mode.TARGET_IMPORT,
        }:
            raise TenantRestoreRefused("Restored recovery state conflicts with target import.")
        state.mode = DeploymentRecoveryState.Mode.TARGET_IMPORT
        state.active_restore = None
        state.quarantine_reason = ""
        state.quarantined_at = None
        state.acknowledged_at = None
        state.acknowledged_by = None
        state.acknowledgement = ""
        state.save(using=using)
    return identity


def reconcile_native_app_registrations(*, using="default", configured_apps=None):
    configured_apps = (
        getattr(settings, "DEVICE_ATTESTATION_APPS", {})
        if configured_apps is None else configured_apps
    )
    expected = []
    if not isinstance(configured_apps, dict):
        raise TenantRestoreRefused("Target native-app configuration is invalid.")
    for platform, registrations in sorted(configured_apps.items()):
        if platform not in {"apple", "android"} or not isinstance(registrations, dict):
            raise TenantRestoreRefused("Target native-app configuration is invalid.")
        for config_key, declaration in sorted(registrations.items()):
            if not isinstance(declaration, dict):
                raise TenantRestoreRefused("Target native-app declaration is invalid.")
            # The configured key is the registration identity used by the live
            # attestation resolver and provisioning command; declaration values hold
            # verifier material, not an alternate authority identifier.
            app_id = str(config_key)
            environments = declaration.get("environments")
            if not app_id or not isinstance(environments, list) or not environments:
                raise TenantRestoreRefused("Target native-app declaration is incomplete.")
            for environment in sorted(set(environments)):
                if environment not in {"development", "production"}:
                    raise TenantRestoreRefused("Target native-app environment is invalid.")
                expected.append((platform, app_id, environment, str(config_key)))
    with transaction.atomic(using=using):
        queryset = NativeAppRegistration.objects.using(using).select_for_update()
        if queryset.exclude(makerspace__isnull=True).exists():
            raise TenantRestoreRefused("Restored tenant-scoped native-app authority survived.")
        queryset.delete()
        NativeAppRegistration.objects.using(using).bulk_create([
            NativeAppRegistration(
                makerspace=None,
                platform=platform,
                app_id=app_id,
                environment=environment,
                verifier_config_key=config_key,
                status=NativeAppRegistration.Status.APPROVED,
            )
            for platform, app_id, environment, config_key in expected
        ])
        actual = tuple(
            NativeAppRegistration.objects.using(using)
            .order_by("platform", "app_id", "environment")
            .values_list("platform", "app_id", "environment", "verifier_config_key")
        )
        if actual != tuple(sorted(expected)):
            raise TenantRestoreRefused("Target native-app authority reconciliation disagrees.")
    return actual


def set_target_normal(*, expected_identity, using="default"):
    connection = connections[using]
    live = query_live_database_identity(connection)
    expected = (
        expected_identity["database_uuid"],
        expected_identity["run_id"],
        expected_identity["artifact_sha256"],
        expected_identity["capture_id"],
    )
    actual = (live.database_uuid, live.run_id, live.artifact_sha256, live.capture_id)
    if actual != expected:
        raise TenantRestoreRefused("Explicit target database identity changed before gate clear.")
    with transaction.atomic(using=using):
        state = DeploymentRecoveryState.objects.using(using).select_for_update().get(pk=1)
        if state.mode != DeploymentRecoveryState.Mode.TARGET_IMPORT:
            raise TenantRestoreRefused("Target recovery mode is not target-import.")
        state.mode = DeploymentRecoveryState.Mode.NORMAL
        state.save(using=using, update_fields=("mode", "updated_at"))
    state.refresh_from_db(using=using)
    if state.mode != DeploymentRecoveryState.Mode.NORMAL:
        raise TenantRestoreRefused("Target recovery mode did not become NORMAL.")
    return state
