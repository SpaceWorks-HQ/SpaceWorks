"""Per-object H1-ledger effects for D7 target object loading."""

import hashlib
import re

from .tenant_restore_types import ObjectEntry, TenantRestoreRefused


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def object_phase(index, entry):
    return f"object-load-{index:06d}-{entry.sha256[:12]}"


def object_phases(entries):
    return tuple(object_phase(index, entry) for index, entry in enumerate(entries))


def validate_object_plan(entries, *, destination_prefix):
    if (
        not isinstance(destination_prefix, str)
        or not destination_prefix
        or destination_prefix.startswith("/")
        or ".." in destination_prefix.split("/")
    ):
        raise TenantRestoreRefused("The object destination prefix is not dedicated.")
    seen = set()
    for entry in entries:
        if (
            not isinstance(entry, ObjectEntry)
            or not isinstance(entry.sha256, str)
            or not SHA256.fullmatch(entry.sha256)
            or not isinstance(entry.bucket, str)
            or not entry.bucket
            or not isinstance(entry.key, str)
            or ".." in entry.key.split("/")
        ):
            raise TenantRestoreRefused("The target object manifest is invalid.")
        identity = (entry.bucket, entry.key)
        if identity in seen or not entry.key.startswith(destination_prefix.rstrip("/") + "/"):
            raise TenantRestoreRefused("The target object prefix is shared or duplicated.")
        if (
            isinstance(entry.size, bool)
            or not isinstance(entry.size, int)
            or entry.size < 0
            or not isinstance(entry.member, str)
            or not entry.member
        ):
            raise TenantRestoreRefused("The target object manifest is incomplete.")
        seen.add(identity)
    return tuple(entries)


def _detail(entry, outcome):
    return {
        "bucket": entry.bucket,
        "key": entry.key,
        "digest": entry.sha256,
        "outcome": outcome,
    }


def _incomplete_begun(ledger, phase):
    records = ledger.records()
    done = {
        (item["phase"], item["attempt"])
        for item in records if item["state"] == "done"
    }
    begun = [
        item for item in records
        if item["phase"] == phase
        and item["state"] == "begun"
        and (item["phase"], item["attempt"]) not in done
    ]
    return begun[-1] if begun else None


def load_object(ledger, store, artifact, entry, *, index):
    """Record the chosen outcome before a write and resume only missing bytes."""
    phase = object_phase(index, entry)
    prior = _incomplete_begun(ledger, phase)
    existing = store.digest(entry.bucket, entry.key)
    if existing is not None and existing != entry.sha256:
        raise TenantRestoreRefused("Existing target object bytes have a different SHA-256.")
    if existing == entry.sha256:
        if prior is not None:
            ledger.finish(prior, prior["detail"])
            return prior["detail"]["outcome"]
        begun = ledger.begin(phase, _detail(entry, "accepted_existing"))
        ledger.finish(begun)
        return "accepted_existing"

    payload = artifact.object_bytes(entry)
    if len(payload) != entry.size or hashlib.sha256(payload).hexdigest() != entry.sha256:
        raise TenantRestoreRefused("Artifact object bytes do not match their manifest.")
    begun = ledger.begin(phase, _detail(entry, "created_by_this_run"))
    store.put(entry, payload)
    if store.digest(entry.bucket, entry.key) != entry.sha256:
        raise TenantRestoreRefused("Target object write did not preserve SHA-256.")
    ledger.finish(begun)
    return "created_by_this_run"


def rollback_created_objects(ledger, store):
    """Never delete accepted-existing bytes, even if the later restore aborts."""
    removed = []
    identities = set()
    for record in ledger.records():
        detail = record["detail"]
        if detail.get("outcome") != "created_by_this_run":
            continue
        identity = (detail.get("bucket"), detail.get("key"), detail.get("digest"))
        if None not in identity:
            identities.add(identity)
    for bucket, key, digest in sorted(identities):
        existing = store.digest(bucket, key)
        if existing is None:
            continue
        if existing != digest:
            raise TenantRestoreRefused(
                "A run-created target object changed; automatic rollback is unsafe."
            )
        store.delete(bucket, key)
        removed.append((bucket, key))
    return tuple(removed)
