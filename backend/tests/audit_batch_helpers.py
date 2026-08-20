from django.utils import timezone

from apps.audit.anchors import (
    AnchorConflict,
    anchors_match,
    rotation_identity,
    validate_rotation_envelope,
)
from apps.audit.batches import (
    activate_scope,
    batch_envelope,
    seal_scope,
)


class MemoryAnchorSink:
    def __init__(self, *, fail_publish=False):
        self.anchors = {}
        self.rotations = {}
        self.fail_publish = fail_publish

    @staticmethod
    def identity(envelope):
        payload = envelope["payload"]
        return (
            payload["deployment_id"],
            payload["scope"],
            payload["signer_fingerprint"],
            payload["batch_seq"],
        )

    def fetch(self, identity):
        return self.anchors.get(identity)

    def publish(self, envelope):
        if self.fail_publish:
            raise RuntimeError("anchor unavailable")
        identity = self.identity(envelope)
        existing = self.anchors.get(identity)
        if existing is not None:
            if not anchors_match(existing, envelope):
                raise AnchorConflict("conflicting sequence")
            return existing
        protocol = envelope["payload"].get("anchor_protocol_version", 1)
        heads = [key[3] for key in self.anchors if key[:2] == identity[:2]]
        if protocol == 1:
            _seq, current_signer, _root = self.fetch_scope_head(
                identity[0], identity[1]
            )
            if current_signer is not None and current_signer != identity[2]:
                raise AnchorConflict("signer is not the scope-global authority")
            heads = [key[3] for key in self.anchors if key[:3] == identity[:3]]
        latest = max(heads, default=-1)
        if protocol == 2 and heads:
            _seq, current_signer, _root = self.fetch_scope_head(
                identity[0], identity[1]
            )
            if current_signer != identity[2]:
                raise AnchorConflict("missing cross-key transition")
        if identity[3] != latest + 1:
            raise AnchorConflict("regressing or gapped sequence")
        stored = {**envelope, "anchored_at": timezone.now().isoformat()}
        self.anchors[identity] = stored
        return stored

    @staticmethod
    def rotation_identity(envelope):
        return rotation_identity(envelope)

    def fetch_rotation(self, identity):
        return self.rotations.get(identity)

    def publish_rotation(self, envelope):
        if self.fail_publish:
            raise RuntimeError("anchor unavailable")
        validate_rotation_envelope(envelope)
        identity = rotation_identity(envelope)
        existing = self.rotations.get(identity)
        if existing is not None:
            if not anchors_match(existing, envelope):
                raise AnchorConflict("conflicting transition")
            return existing
        head_seq, head_signer, head_root = self.fetch_scope_head(
            identity[0], identity[1]
        )
        if head_signer is None:
            raise AnchorConflict("scope has no anchor head")
        if head_seq != identity[4] or head_signer != identity[2]:
            raise AnchorConflict("transition does not bind scope head")
        if head_root.hex() != envelope["payload"]["last_old_batch_root"]:
            raise AnchorConflict("transition root differs from scope head")
        stored = {**envelope, "anchored_at": timezone.now().isoformat()}
        self.rotations[identity] = stored
        return stored

    def fetch_scope_head(self, deployment_id, scope):
        heads = [key for key in self.anchors if key[:2] == (deployment_id, scope)]
        if not heads:
            return -1, None, None
        sequence = max(key[3] for key in heads)
        head = next(key for key in heads if key[3] == sequence)
        signer = head[2]
        envelope = self.anchors[head]
        root = bytes.fromhex(envelope["payload"].get("merkle_root", "00" * 32))
        transitions = {
            identity[2]: identity[3]
            for identity in self.rotations
            if identity[:2] == (deployment_id, scope) and identity[4] == sequence
        }
        visited = set()
        while signer in transitions:
            if signer in visited:
                raise AnchorConflict("cyclic transition history")
            visited.add(signer)
            signer = transitions[signer]
        return sequence, signer, root


def activate_and_seal(makerspace_id, sink):
    key = activate_scope(makerspace_id, sink)
    batch = seal_scope(makerspace_id, key)
    if batch is not None:
        sink.publish(batch_envelope(batch))
    return key, batch
