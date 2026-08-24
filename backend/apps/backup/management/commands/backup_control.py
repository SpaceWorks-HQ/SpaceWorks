import json
from pathlib import Path
from datetime import timedelta
import hashlib
import hmac
import re
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone

from apps.backup import storage
from apps.backup.models import DeploymentRecoveryState, RestoreOperation
from apps.backup.backup_control_preflight import run_restore_preflight
from apps.backup.management.commands.backup_preflight import (
    build_info,
    check_setting_policies,
)
from apps.backup.recovery import enter_quarantine
from apps.backup.object_restore import (
    cleanup_rollback_objects,
    reconcile_rollback_journal,
    restore_objects,
    rollback_objects,
)
from apps.backup.restore_diff import compute_restore_diff
from apps.backup.restore_control_records import (
    export_control_record,
    rehydrate_control_record,
    validate_restored_state,
)
from apps.backup.restore_services import (
    claim_restore,
    enter_quiescence,
    prepare_restore_resume,
    set_stage,
)


class Command(BaseCommand):
    help = "Privileged-host coordination surface for backup restore."
    _build_info = staticmethod(build_info)
    _check_setting_policies = staticmethod(check_setting_policies)
    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest="action", required=True)
        for name in ("claim", "preflight", "quiesce", "decision", "complete", "fail", "quarantine", "validate", "pause"):
            command = actions.add_parser(name)
            command.add_argument("restore_id")
        actions.choices["fail"].add_argument("--message", required=True)
        actions.choices["pause"].add_argument("--message", required=True)
        actions.choices["quarantine"].add_argument("--reason", required=True)
        actions.choices["preflight"].add_argument("--current-oci-digest", default="")
        actions.choices["preflight"].add_argument("--manifest", required=True)
        actions.choices["preflight"].add_argument("--bundle")
        actions.choices["preflight"].add_argument("--encrypted-file")
        actions.choices["preflight"].add_argument("--decrypted-bundle")
        actions.choices["preflight"].add_argument("--continuity-secrets")
        export = actions.add_parser("export-archive")
        export.add_argument("restore_id")
        export.add_argument("--output", required=True)
        diff = actions.add_parser("diff-wait")
        diff.add_argument("restore_id")
        diff.add_argument("--archive-database-name", required=True)
        describe = actions.add_parser("describe")
        describe.add_argument("restore_id")
        rehydrate = actions.add_parser("rehydrate")
        rehydrate.add_argument("restore_id")
        rehydrate.add_argument("--archive-id", required=True)
        rehydrate.add_argument("--kind", required=True, choices=RestoreOperation.Kind.values)
        rehydrate.add_argument("--requested-by", required=True, type=int)
        rehydrate.add_argument("--control-record", required=True)
        rehydrate.add_argument("--manifest", required=True)
        export_control = actions.add_parser("export-control")
        export_control.add_argument("restore_id")
        export_control.add_argument("--output", required=True)
        export_control.add_argument("--decision", choices=RestoreOperation.Decision.values)
        objects = actions.add_parser("restore-objects")
        objects.add_argument("restore_id")
        objects.add_argument("--bundle-root", required=True)
        objects.add_argument("--manifest", required=True)
        objects.add_argument("--journal", required=True)
        rollback = actions.add_parser("rollback-objects")
        rollback.add_argument("restore_id")
        cleanup = actions.add_parser("cleanup-rollback")
        cleanup.add_argument("restore_id")
        reconcile = actions.add_parser("reconcile-journal")
        reconcile.add_argument("restore_id")
        reconcile.add_argument("--journal", required=True)
        stage = actions.add_parser("stage")
        stage.add_argument("restore_id")
        stage.add_argument("value", choices=RestoreOperation.Stage.values)

    def handle(self, *args, **options):
        action = options["action"]
        restore_id = options["restore_id"]
        if action == "claim":
            claimed = claim_restore(restore_id)
            if claimed:
                self.stdout.write("claimed")
            elif prepare_restore_resume(restore_id):
                self.stdout.write("resume")
            else:
                self.stdout.write("skip")
        elif action == "preflight":
            self._preflight(
                restore_id,
                options["manifest"],
                options["current_oci_digest"],
                options.get("bundle"),
                options.get("encrypted_file"),
                options.get("decrypted_bundle"),
                options.get("continuity_secrets"),
            )
        elif action == "quiesce":
            enter_quiescence(restore_id)
            self.stdout.write(str(settings.BACKUP_PRESIGN_DRAIN_SECONDS))
        elif action == "decision":
            restore = RestoreOperation.objects.get(pk=restore_id)
            self.stdout.write(restore.decision)
        elif action == "complete":
            set_stage(restore_id, RestoreOperation.Stage.COMPLETED)
            self.stdout.write("complete")
        elif action == "fail":
            set_stage(restore_id, RestoreOperation.Stage.FAILED, error=options["message"])
            self._normal_mode()
            self.stdout.write("failed")
        elif action == "pause":
            if not prepare_restore_resume(restore_id, options["message"]):
                raise CommandError("This restore stage cannot be resumed safely.")
            self.stdout.write("paused")
        elif action == "quarantine":
            restore = RestoreOperation.objects.get(pk=restore_id)
            enter_quarantine(restore, options["reason"])
            self.stdout.write("quarantined")
        elif action == "validate":
            try:
                validate_restored_state(restore_id)
            except RuntimeError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write("validation-ok")
        elif action == "export-archive":
            self._export_archive(restore_id, options["output"])
        elif action == "diff-wait":
            self._diff_wait(restore_id, options["archive_database_name"])
        elif action == "describe":
            restore = RestoreOperation.objects.get(pk=restore_id)
            self.stdout.write(json.dumps({
                "restore_id": str(restore.pk), "archive_id": str(restore.archive_id),
                "kind": restore.kind, "requested_by": restore.requested_by_id,
                "stage": restore.stage,
            }))
        elif action == "rehydrate":
            rehydrate_control_record(restore_id, options)
            self.stdout.write("rehydrated")
        elif action == "export-control":
            path = export_control_record(
                restore_id, options["output"], options.get("decision")
            )
            self.stdout.write(str(path))
        elif action == "restore-objects":
            restore = RestoreOperation.objects.get(pk=restore_id)
            manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
            set_stage(restore_id, RestoreOperation.Stage.OBJECTS_RESTORING)
            restore_objects(restore, options["bundle_root"], manifest, options["journal"])
            self.stdout.write("objects-restored")
        elif action == "rollback-objects":
            rollback_objects(RestoreOperation.objects.get(pk=restore_id))
            self.stdout.write("objects-rolled-back")
        elif action == "cleanup-rollback":
            cleanup_rollback_objects(RestoreOperation.objects.get(pk=restore_id))
            self.stdout.write("rollback-cleaned")
        elif action == "reconcile-journal":
            count = reconcile_rollback_journal(
                RestoreOperation.objects.get(pk=restore_id), options["journal"]
            )
            self.stdout.write(str(count))
        elif action == "stage":
            set_stage(restore_id, options["value"])
            self.stdout.write(options["value"])

    def _preflight(
        self, restore_id, manifest_path, current_oci_digest="", bundle_path=None,
        encrypted_file=None, decrypted_bundle=None, continuity_secrets=None,
    ):
        result = run_restore_preflight(
            restore_id,
            manifest_path,
            current_oci_digest=current_oci_digest,
            bundle_path=bundle_path,
            encrypted_file=encrypted_file,
            decrypted_bundle=decrypted_bundle,
            continuity_secrets=continuity_secrets,
            build_info=self._build_info,
            check_setting_policies=self._check_setting_policies,
        )
        self.stdout.write(result)

    def _export_archive(self, restore_id, output):
        restore = RestoreOperation.objects.select_related("archive").get(pk=restore_id)
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = storage.open_archive(restore.archive.object_key)
        digest = hashlib.sha256()
        with path.open("wb") as handle:
            while chunk := body.read(1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
        expected = restore.archive.archive_sha256
        if expected and not hmac.compare_digest(digest.hexdigest(), expected):
            path.unlink(missing_ok=True)
            raise CommandError("The exported archive sha256 does not match the stored digest.")
        self.stdout.write(str(path))

    def _diff_wait(self, restore_id, archive_database_name):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,62}", archive_database_name):
            raise CommandError("The archive diff database name is invalid.")
        connections.databases["archive_restore"] = dict(settings.DATABASES["default"])
        connections.databases["archive_restore"]["NAME"] = archive_database_name
        connections.databases["restore_control"] = dict(settings.DATABASES["default"])

        def wait_for_decision(report):
            deadline = timezone.now() + timedelta(seconds=settings.BACKUP_DECISION_SECONDS)
            with connections["restore_control"].cursor() as cursor:
                cursor.execute(
                    "UPDATE backup_restoreoperation SET restore_diff=%s, decision_deadline_at=%s, updated_at=%s WHERE id=%s",
                    [json.dumps(report), deadline, timezone.now(), restore_id],
                )
            while timezone.now() < deadline:
                with connections["restore_control"].cursor() as cursor:
                    cursor.execute("SELECT decision FROM backup_restoreoperation WHERE id=%s", [restore_id])
                    decision = cursor.fetchone()[0]
                if decision != RestoreOperation.Decision.PENDING:
                    self.stdout.write(decision)
                    return
                time.sleep(1)
            with connections["restore_control"].cursor() as cursor:
                cursor.execute(
                    "UPDATE backup_restoreoperation SET decision=%s, stage=%s, error_detail=%s, completed_at=%s, updated_at=%s WHERE id=%s",
                    [RestoreOperation.Decision.ABORT, RestoreOperation.Stage.ABORTED, "The bounded decision window expired.", timezone.now(), timezone.now(), restore_id],
                )
                cursor.execute(
                    "UPDATE backup_deploymentrecoverystate SET mode=%s, active_restore_id=NULL, updated_at=%s WHERE id=1",
                    [DeploymentRecoveryState.Mode.NORMAL, timezone.now()],
                )
            self.stdout.write("abort")

        compute_restore_diff(
            archive_using="archive_restore",
            within_snapshot=wait_for_decision,
        )

    @staticmethod
    def _normal_mode():
        DeploymentRecoveryState.objects.filter(pk=1).update(
            mode=DeploymentRecoveryState.Mode.NORMAL, active_restore=None
        )
