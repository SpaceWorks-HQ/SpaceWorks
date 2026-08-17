"""Exact-closure admission for PORTABLE identity disclosure."""

import hashlib
import json

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.accounts.models import User
from apps.data_export.datasets import DATASETS
from apps.data_export.fields import USER_PROJECTIONS
from apps.data_export.references import USER_EDGES
from apps.data_export.types import Fidelity

from .models_protocol import DisclosureClosureApproval
from .protocol_errors import ClosureAdmissionError, ClosureChangedError
from .row_conditions import condition_matches
from .target_projection import ROW_POLICIES, RowDisposition


def export_row_policy(model_label, row):
    """Return ``(emit_row, contributes_live_edges)`` before closure traversal."""
    if model_label == "audit.AuditLog" and row.action.startswith("tenant_migration."):
        # Migration coordination audit remains append-only on the source deployment,
        # but carrying it would make the act of reviewing/approving a closure change
        # that same closure through the audit actor edge.
        return False, False
    policy = ROW_POLICIES.get(model_label)
    if policy is None or not condition_matches(policy.condition, row):
        return True, True
    if policy.disposition is RowDisposition.DROP:
        # Source-controlled PORTABLE exports omit rows that can never become live,
        # while import applies the same refusal independently because crafted and
        # older archives are not under the source exporter's control.
        return False, False
    if policy.disposition in {
        RowDisposition.STAGE_INERT,
        RowDisposition.KEEP_TARGET,
    }:
        return True, False
    return True, True


def canonical_identities(user_rows):
    names = USER_PROJECTIONS[Fidelity.PORTABLE]
    identities = []
    for user in sorted(user_rows, key=lambda item: str(item.pk)):
        identity = {}
        for name in sorted(names):
            value = getattr(user, name)
            identity[name] = value.isoformat() if hasattr(value, "isoformat") else value
        identities.append(identity)
    return identities


def closure_digest(identities):
    payload = json.dumps(
        identities, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_pending_closure(makerspace):
    """Compute the exact projected identity list shown to the source superadmin."""
    closure = set()
    for dataset in DATASETS.values():
        if dataset.fidelity is not Fidelity.PORTABLE or dataset.model == "accounts.User":
            continue
        model = apps.get_model(dataset.model)
        rows = model.objects.filter(dataset.predicate.as_q(makerspace.pk))
        for row in rows.iterator(chunk_size=500):
            emit, contributes = export_row_policy(dataset.model, row)
            if emit and contributes:
                closure.update(_row_user_ids(dataset.model, row))
    users = apps.get_model("accounts.User").objects.filter(pk__in=closure)
    identities = canonical_identities(users)
    return {"digest": closure_digest(identities), "identities": identities}


@transaction.atomic
def approve_closure(*, actor, makerspace, digest, decisions):
    _require_superadmin(actor)
    current = compute_pending_closure(makerspace)
    if digest != current["digest"]:
        raise ClosureChangedError("The disclosure closure changed; review it again.")
    identity_ids = [str(item["id"]) for item in current["identities"]]
    decision_map = {str(item["user_id"]): bool(item["approved"]) for item in decisions}
    if set(decision_map) != set(identity_ids):
        raise ClosureAdmissionError("A decision is required for every identity in the closure.")
    approval = DisclosureClosureApproval.objects.create(
        makerspace=makerspace,
        closure_digest=digest,
        identity_ids=identity_ids,
        approved_identity_ids=[value for value in identity_ids if decision_map[value]],
        approved_by=actor,
    )
    audit.record(
        actor,
        "tenant_migration.disclosure_approved",
        makerspace=makerspace,
        target=approval,
        meta={
            "closure_digest": digest,
            "identity_count": len(identity_ids),
            "approved_count": len(approval.approved_identity_ids),
            "format_version": 1,
        },
    )
    return approval


@transaction.atomic
def revoke_approval(*, actor, approval):
    _require_superadmin(actor)
    locked = DisclosureClosureApproval.objects.select_for_update().get(pk=approval.pk)
    if locked.revoked_at is None:
        locked.revoked_at = timezone.now()
        locked.revoked_by = actor
        locked.save(update_fields=("revoked_at", "revoked_by"))
        audit.record(
            actor,
            "tenant_migration.disclosure_revoked",
            makerspace=locked.makerspace,
            target=locked,
            meta={"closure_digest": locked.closure_digest, "format_version": 1},
        )
    return locked


def validate_snapshot_approval(approval, identities):
    digest = closure_digest(identities)
    ids = [str(item["id"]) for item in identities]
    approved = {str(value) for value in approval.approved_identity_ids}
    if (
        approval.revoked_at is not None
        or approval.closure_digest != digest
        or approval.identity_ids != ids
        or not approved.issubset(ids)
    ):
        raise ClosureChangedError(
            "The disclosure closure changed after approval; the export was refused."
        )
    return {int(value) for value in approved}


def withheld_edges(dataset_rows, denied_ids):
    withheld = set()
    for dataset, rows in dataset_rows:
        for row, _dangling in rows:
            for field_name, user_id in _row_user_edges(dataset.model, row):
                if user_id not in denied_ids:
                    continue
                field = _model_field(dataset.model, field_name)
                if field is None or not getattr(field, "null", False):
                    raise ClosureAdmissionError(
                        f"Withheld identity is required by {dataset.model}.{field_name}.",
                        model=dataset.model,
                        edge=field_name,
                    )
                withheld.add((dataset.model, row.pk, field_name))
    return withheld


def _row_user_ids(model_label, row):
    return {value for _field, value in _row_user_edges(model_label, row)}


def _row_user_edges(model_label, row):
    for (fidelity, label, field_name), edge in USER_EDGES.items():
        if fidelity is not Fidelity.PORTABLE or label != model_label or not edge.included:
            continue
        field = _model_field(model_label, field_name)
        value = getattr(row, field_name if edge.raw else field.attname, None)
        if value:
            yield field_name, int(value)


def _model_field(model_label, field_name):
    try:
        return apps.get_model(model_label)._meta.get_field(field_name)
    except Exception:
        return None


def _require_superadmin(actor):
    if not (
        getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) == User.Role.SUPERADMIN
    ):
        raise ClosureAdmissionError("Only a source superadmin may approve disclosure.")
