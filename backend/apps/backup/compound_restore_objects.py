"""Validation and execution of pre-journalled readable-main object effects."""

from .compound_restore_types import CompoundRestoreRefused


def validate_object_effects(effects):
    required = {"bucket", "key", "digest", "outcome"}
    seen = set()
    for item in effects:
        digest = item.get("digest") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or set(item) != required
            or item["outcome"] not in {
                "created_by_this_run", "accepted_existing"
            }
            or not all(isinstance(item[name], str) and item[name] for name in required)
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or item["key"].startswith("/")
            or ".." in item["key"].split("/")
            or (item["bucket"], item["key"]) in seen
        ):
            raise CompoundRestoreRefused(
                "The main-object effect plan is incomplete or duplicated."
            )
        seen.add((item["bucket"], item["key"]))


def restore_objects(object_store, artifact, manifest, effects):
    restored = tuple(object_store.restore_main(
        artifact, manifest, effects
    ))
    if restored != effects:
        raise CompoundRestoreRefused(
            "The restored object effects differ from the pre-journalled plan."
        )
    return {"effects": list(restored)}
