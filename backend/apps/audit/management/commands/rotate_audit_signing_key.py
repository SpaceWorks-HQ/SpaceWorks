"""Operator command for resumable Ed25519 audit signing-key rotation."""

import json
import logging
import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.audit import services as audit
from apps.audit.anchors import configured_sink
from apps.audit.models import AuditSigningKey
from apps.audit.rotations import (
    finalize_rotation,
    latest_rotation_state,
    prepare_rotation,
    publish_rotation,
    scope_head,
)
from apps.makerspaces.models import Makerspace


logger = logging.getLogger(__name__)
HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")
TERMINAL_STATES = {"FINALIZED", "ABORTED"}


class Command(BaseCommand):
    help = "Rotate one scope's audit Ed25519 signing key without accepting key material."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--global", action="store_true", dest="global_scope")
        scope.add_argument("--makerspace-id", type=int)
        parser.add_argument("--actor-user-id", type=int, required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--execute", action="store_true")
        parser.add_argument("--expected-current-fingerprint")
        parser.add_argument("--expected-head-seq", type=int)
        parser.add_argument("--expected-head-root")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            pk=options["actor_user_id"], is_active=True, is_superuser=True
        ).first()
        if actor is None:
            raise CommandError("--actor-user-id must reference an active superuser.")
        makerspace_id = self._scope(options)
        key = AuditSigningKey.objects.filter(
            makerspace_id=makerspace_id, is_active=True
        ).first()
        if key is None:
            raise CommandError("The scope has no active audit signing key.")
        head_seq, head_root = scope_head(makerspace_id)
        if options["dry_run"]:
            self.stdout.write(json.dumps({
                "scope": "global" if makerspace_id is None else makerspace_id,
                "current_fingerprint": key.fingerprint,
                "current_version": key.version,
                "head_seq": head_seq,
                "head_root": head_root.hex(),
                "pending_rotation_id": (
                    str(key.pending_rotation_id) if key.pending_rotation_id else None
                ),
            }, sort_keys=True))
            return
        fingerprint, expected_seq, expected_root = self._expectations(options)
        rotation = None
        try:
            sink = configured_sink()
            rotation, created = prepare_rotation(
                makerspace_id,
                expected_fingerprint=fingerprint,
                expected_head_seq=expected_seq,
                expected_head_root=expected_root,
            )
            meta = self._meta(rotation)
            if created:
                audit.record(
                    actor,
                    "audit.signing_key_rotation_started",
                    makerspace=rotation.makerspace,
                    meta=meta,
                )
            publish_rotation(rotation, sink)
            finalize_rotation(rotation, sink)
            audit.record(
                actor,
                "audit.signing_key_rotation_completed",
                makerspace=rotation.makerspace,
                meta=meta,
            )
        except Exception as exc:  # noqa: BLE001 - operator gets one typed command error
            logger.exception(
                "audit_signing_key_rotation_failed",
                extra={
                    "makerspace_id": makerspace_id,
                    "rotation_id": str(rotation.pk) if rotation is not None else None,
                },
            )
            if rotation is not None and latest_rotation_state(rotation) not in TERMINAL_STATES:
                audit.record(
                    actor,
                    "audit.signing_key_rotation_failed",
                    makerspace=rotation.makerspace,
                    meta=self._meta(rotation),
                )
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Rotated audit signing key to {rotation.new_fingerprint}."
        ))

    def _scope(self, options):
        if options["global_scope"]:
            return None
        makerspace_id = options["makerspace_id"]
        if makerspace_id is None or makerspace_id < 1:
            raise CommandError("--makerspace-id must be a positive integer.")
        if not Makerspace.objects.filter(pk=makerspace_id).exists():
            raise CommandError("The makerspace does not exist.")
        return makerspace_id

    def _expectations(self, options):
        fingerprint = options["expected_current_fingerprint"]
        sequence = options["expected_head_seq"]
        root = options["expected_head_root"]
        if not fingerprint or not HEX_64.fullmatch(fingerprint):
            raise CommandError("--expected-current-fingerprint must be 64 hex characters.")
        if sequence is None or sequence < 0:
            raise CommandError("--expected-head-seq must be zero or greater.")
        if not root or not HEX_64.fullmatch(root):
            raise CommandError("--expected-head-root must be 64 hex characters.")
        return fingerprint.lower(), sequence, bytes.fromhex(root)

    @staticmethod
    def _meta(rotation):
        return {
            "rotation_id": str(rotation.pk),
            "old_fingerprint": rotation.old_fingerprint,
            "new_fingerprint": rotation.new_fingerprint,
            "old_version": rotation.old_version,
            "new_version": rotation.new_version,
            "last_old_batch_seq": rotation.last_old_batch_seq,
            "last_old_batch_root": bytes(rotation.last_old_batch_root).hex(),
        }
