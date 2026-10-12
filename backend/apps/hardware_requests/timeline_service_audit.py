"""Audit rows and evidence-retention state for the existing request timeline.

Correlation is deliberately narrow. A row belongs to a request when it targets the
request directly, or when its action's catalogue entry declares a meta path that
``AUDIT_META_REFERENCES`` remaps to ``HardwareRequest`` and that path holds this
request's PK. Arbitrary JSON keys are never scanned, and the HTTP correlation id
(``spaceworks_request_id``) is not a domain relationship at all.
"""

from django.db.models import Q

from apps.audit.models import AuditLog
from apps.audit.presentation import project, request_reference_paths
from apps.audit.presentation_catalog import PRESENTATION_CATALOG
from apps.evidence.models import EvidenceObjectRetentionState

REQUEST_TARGET_TYPE = "hardware_requests.hardwarerequest"


def _reference_clauses(request_pk):
    clauses = Q()
    for action in PRESENTATION_CATALOG:
        for path in request_reference_paths(action):
            lookup = "meta__" + "__".join(path.split("."))
            # Stored integers and stringified integers both occur in historical rows.
            clauses |= Q(action=action, **{lookup: request_pk})
            clauses |= Q(action=action, **{lookup: str(request_pk)})
    return clauses


def request_audit_rows(hardware_request):
    query = Q(target_type=REQUEST_TARGET_TYPE, target_id=str(hardware_request.pk))
    query |= _reference_clauses(hardware_request.pk)
    return (
        AuditLog.objects.filter(makerspace_id=hardware_request.makerspace_id)
        .filter(query)
        .select_related("actor")
        .order_by("created_at", "pk")
    )


def audit_events(hardware_request, make_event):
    events = []
    for row in request_audit_rows(hardware_request):
        projection = project(row)
        events.append(
            make_event(
                "audit",
                row.created_at,
                row.actor,
                row.pk,
                {
                    "request_id": hardware_request.pk,
                    "action": row.action,
                    "action_label": projection.action_label,
                    "meta": projection.meta,
                    "meta_redacted": projection.meta_redacted,
                    "target_link": projection.target_link,
                },
            )
        )
    return events


def attach_evidence_retention(events):
    """One bulk lookup; ``None`` means only "no retention-state row", never "available"."""
    evidence_ids = {event["evidence_id"] for event in events if event.get("evidence_id")}
    states = {
        row.evidence_id: row
        for row in EvidenceObjectRetentionState.objects.filter(evidence_id__in=evidence_ids)
    }
    for event in events:
        state = states.get(event.get("evidence_id"))
        event["evidence_retention"] = (
            None
            if state is None
            else {"state": state.status, "object_expired_at": state.object_expired_at}
        )
    return events
