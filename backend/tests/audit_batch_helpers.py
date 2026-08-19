from django.utils import timezone

from apps.audit.anchors import AnchorConflict, anchors_match
from apps.audit.batches import (
    activate_scope,
    batch_envelope,
    seal_scope,
)


class MemoryAnchorSink:
    def __init__(self, *, fail_publish=False):
        self.anchors = {}
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
        heads = [
            key[3]
            for key in self.anchors
            if key[:3] == identity[:3]
        ]
        latest = max(heads, default=-1)
        if identity[3] != latest + 1:
            raise AnchorConflict("regressing or gapped sequence")
        stored = {**envelope, "anchored_at": timezone.now().isoformat()}
        self.anchors[identity] = stored
        return stored


def activate_and_seal(makerspace_id, sink):
    key = activate_scope(makerspace_id, sink)
    batch = seal_scope(makerspace_id, key)
    if batch is not None:
        sink.publish(batch_envelope(batch))
    return key, batch
