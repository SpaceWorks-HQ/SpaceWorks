"""The one permitted EvidencePhoto UPDATE: a one-way mark that a workflow consumed it.

``consumption_state`` is the durable, positive proof abandoned-upload cleanup relies
on. Every consuming workflow calls ``mark_consumed`` inside its own attachment
transaction, after ``lock_evidence_for_attachment`` has taken the evidence lock order,
so the mark commits or rolls back with the relationship/audit it accompanies. The
PostgreSQL guard (evidence migration 0007) permits exactly this transition with every
other column unchanged; nothing else may update a photo.
"""

from django.db import transaction

from apps.evidence.models import EvidencePhoto


CONSUMABLE_STATES = (
    EvidencePhoto.ConsumptionState.LEGACY_UNKNOWN,
    EvidencePhoto.ConsumptionState.UNCONSUMED,
)


def mark_consumed(evidence):
    """Idempotently move ``evidence`` to CONSUMED; returns True when it changed."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("mark_consumed must run inside the consuming transaction.")
    evidence_id = getattr(evidence, "pk", evidence)
    current = (
        EvidencePhoto.objects.select_for_update()
        .values_list("consumption_state", flat=True)
        .get(pk=evidence_id)
    )
    if current == EvidencePhoto.ConsumptionState.CONSUMED:
        return False
    changed = EvidencePhoto.objects.filter(
        pk=evidence_id, consumption_state__in=CONSUMABLE_STATES
    ).update(consumption_state=EvidencePhoto.ConsumptionState.CONSUMED)
    if isinstance(evidence, EvidencePhoto):
        evidence.consumption_state = EvidencePhoto.ConsumptionState.CONSUMED
    return bool(changed)
