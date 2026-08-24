"""Eight-step delayed, tenant-authorized, fill-only slice merge."""

from pathlib import Path
import tempfile

from apps.backup.models import B1RestoreComponentState
from apps.backup.slice_merge_database import (
    component_locks,
    merge_schema_name,
    provision_merge_role,
)
from apps.backup.slice_merge_cleanup import drop_staging_schema, staging_schema_exists
from apps.backup.slice_merge_deks import install_target_deks, verify_target_deks
from apps.backup.slice_merge_identity import (
    decrypt_file,
    read_identity,
    recipient_fingerprint,
    zeroize,
)
from apps.backup.slice_merge_objects import (
    MergeJournal,
    cleanup_staging,
    promote_objects,
    stage_objects,
    verify_promoted,
)
from apps.backup.slice_merge_staging import (
    add_target_deks,
    apply_staged,
    stage_group,
    verify_staged_rows,
)
from apps.backup.slice_merge_state import (
    CHECKPOINT_RANK as _CHECKPOINT_RANK,
    begin_merging as _begin_merging,
    checkpoint as _checkpoint,
    common_checkpoint as _common_checkpoint,
    dependency_wait as _dependency_wait,
    finalize as _finalize,
    locked_state as _locked_state,
    mark_failed as _mark_failed,
    record_and_resolve_dependencies as _record_and_resolve_dependencies,
    validate_component_states as _validate_component_states,
    verify_constraints_and_reservations as _verify_constraints_and_reservations,
)
from apps.backup.slice_merge_types import (
    BOUNDARY_FINAL,
    BOUNDARY_KEYS,
    BOUNDARY_OBJECTS,
    BOUNDARY_ROWS,
    BOUNDARY_STAGED,
    SliceMergeError,
    SliceMergeInput,
    SliceMergeInterrupted,
    ValidatedSlice,
)
from apps.backup.slice_merge_validation import (
    dependency_facts,
    extract_slice,
    validate_outer,
    validate_plaintext,
)


def merge_slices(
    operation_id, outer_manifest, inputs, *, journal_path, scratch_parent=None,
    boundary_hook=None, using="default",
):
    """Merge one component or one complete cross-linked component group."""
    requested = tuple(inputs)
    if not requested or len({item.component_id for item in requested}) != len(requested):
        raise SliceMergeError("A merge requires one private identity channel per component.")
    all_ids = tuple(B1RestoreComponentState.objects.using(using).filter(
        operation_id=operation_id
    ).values_list("component_id", flat=True))
    journal = MergeJournal(journal_path)
    identities = []
    staged_objects = []
    components = []
    merge_started = False
    schema = merge_schema_name(operation_id, [item.component_id for item in requested])
    rows_committed = False
    with component_locks(operation_id, all_ids, using=using):
        try:
            operation, components = _locked_state(
                operation_id, [item.component_id for item in requested], using=using
            )
            _validate_component_states(operation, components)
            by_id = {item.component_id: item for item in requested}
            outer_facts = {}
            for component in components:
                identity = read_identity(by_id[component.component_id].identity_channel)
                identities.append(identity)
                fingerprint = recipient_fingerprint(identity)
                outer_facts[component.component_id] = validate_outer(
                    operation, component, outer_manifest,
                    by_id[component.component_id].ciphertext_path, fingerprint,
                )
            provision_merge_role(using=using)
            _begin_merging(components, using=using)
            merge_started = True
            with tempfile.TemporaryDirectory(
                prefix="spaceworks-b1-merge-", dir=scratch_parent
            ) as temporary:
                scratch = Path(temporary)
                scratch.chmod(0o700)
                validated = []
                for component, identity in zip(components, identities, strict=True):
                    component_root = scratch / str(component.component_id)
                    component_root.mkdir(mode=0o700)
                    plain_tar = component_root / "slice.tar"
                    decrypt_file(
                        by_id[component.component_id].ciphertext_path,
                        plain_tar, identity,
                    )
                    root = component_root / "slice"
                    root.mkdir(mode=0o700)
                    extract_slice(plain_tar, root)
                    plain_tar.unlink(missing_ok=True)
                    detailed = validate_plaintext(
                        root, component, outer_facts[component.component_id], outer_manifest
                    )
                    validated.append(ValidatedSlice(
                        component, outer_facts[component.component_id], root, detailed, identity
                    ))
                if staging_schema_exists(schema, using=using):
                    drop_staging_schema(schema, using=using)
                group = stage_group(schema, validated, using=using)
                staged_objects = stage_objects(
                    validated, operation_id, journal, accumulator=staged_objects
                )
                _checkpoint(components, "staged", using=using)
                _boundary(boundary_hook, BOUNDARY_STAGED)

                target_deks = {
                    item.component.component_id: install_target_deks(item)
                    for item in validated
                }
                group = add_target_deks(group, target_deks, using=using)
                _checkpoint(components, "keys_installed", using=using)
                _boundary(boundary_hook, BOUNDARY_KEYS)

                facts = {
                    item.component.component_id: dependency_facts(
                        item.root, item.component, outer_manifest
                    )
                    for item in validated
                }
                missing = _record_and_resolve_dependencies(
                    operation_id, components, facts, using=using
                )
                if missing:
                    try:
                        cleanup_staging(staged_objects, strict=True)
                    except SliceMergeError:
                        rows_committed = True
                        raise
                    drop_staging_schema(schema, using=using)
                    journal.replace(
                        "dependency_wait", operation_id=operation_id,
                        component_ids=[item.component_id for item in components],
                        required_component_ids=sorted(map(str, missing)),
                    )
                    _dependency_wait(components, using=using)
                    return {"state": "dependency_wait", "required_component_ids": sorted(map(str, missing))}
                for identity in identities:
                    zeroize(identity)
                identities.clear()

                checkpoint = _common_checkpoint(components, using=using)
                if _CHECKPOINT_RANK[checkpoint] < _CHECKPOINT_RANK["rows_applied"]:
                    apply_staged(group, operation_id, using=using)
                    rows_committed = True
                    _checkpoint(components, "rows_applied", using=using)
                rows_committed = True
                _boundary(boundary_hook, BOUNDARY_ROWS)

                checkpoint = _common_checkpoint(components, using=using)
                if _CHECKPOINT_RANK[checkpoint] < _CHECKPOINT_RANK["objects_promoted"]:
                    promote_objects(staged_objects, journal)
                    _checkpoint(components, "objects_promoted", using=using)
                verify_promoted(staged_objects)
                _boundary(boundary_hook, BOUNDARY_OBJECTS)

                verify_staged_rows(group, using=using)
                for rows in target_deks.values():
                    verify_target_deks(rows, using=using)
                _verify_constraints_and_reservations(operation_id, components, using=using)
                _checkpoint(components, "verified", using=using)
                cleanup_staging(staged_objects, strict=True)
                _boundary(boundary_hook, BOUNDARY_FINAL)
                journal.append(
                    "final_commit_intent", operation_id=operation_id,
                    component_ids=[item.component_id for item in components],
                )
                _finalize(operation_id, components, schema, using=using)
            return {"state": "restored", "component_ids": [str(item.component_id) for item in components]}
        except SliceMergeInterrupted:
            raise
        except Exception as exc:
            if not merge_started:
                pass
            elif not rows_committed:
                try:
                    cleanup_staging(staged_objects, strict=True)
                    if staging_schema_exists(schema, using=using):
                        drop_staging_schema(schema, using=using)
                except Exception:
                    journal.append(
                        "resume_required", operation_id=operation_id,
                        component_ids=[item.component_id for item in components],
                    )
                    raise SliceMergeError(
                        "Terminal cleanup could not prove plaintext staging was discarded."
                    ) from None
                _mark_failed(
                    operation_id, [item.component_id for item in components], using=using
                )
            else:
                journal.append(
                    "resume_required", operation_id=operation_id,
                    component_ids=[item.component_id for item in components],
                )
            if isinstance(exc, SliceMergeError):
                raise
            raise SliceMergeError("The delayed slice merge failed closed.") from None
        finally:
            for identity in identities:
                zeroize(identity)


def _boundary(hook, name):
    if hook is not None:
        hook(name)
