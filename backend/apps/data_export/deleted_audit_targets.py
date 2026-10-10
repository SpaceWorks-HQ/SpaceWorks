"""Prove which dangling EvidencePhoto audit targets were cleaned abandoned uploads.

Old ``evidence.upload_url_issued``/``evidence.viewed`` rows keep naming a photo that
abandoned-upload cleanup later deleted. Such a target becomes inert source provenance
ONLY when an immutable same-tenant ``evidence.abandoned_upload_deleted`` audit names
that exact ID. Any other missing EvidencePhoto target fails closed, as before.
"""

from django.apps import apps

from .errors import ExportIntegrityError

EVIDENCE_TARGET_TYPE = "evidence.evidencephoto"
CLEANUP_ACTION = "evidence.abandoned_upload_deleted"


def cleaned_evidence_targets(makerspace_id, rows):
    """Return the set of target_id strings that are proven-cleaned for these rows."""
    wanted = {
        str(row.target_id)
        for row in rows
        if row.target_id and str(row.target_type).lower() == EVIDENCE_TARGET_TYPE
    }
    if not wanted:
        return set()
    EvidencePhoto = apps.get_model("evidence", "EvidencePhoto")
    AuditLog = apps.get_model("audit", "AuditLog")
    numeric = {value for value in wanted if value.isdigit()}
    present = {
        str(pk)
        for pk in EvidencePhoto.objects.filter(
            makerspace_id=makerspace_id, pk__in=[int(value) for value in numeric]
        ).values_list("pk", flat=True)
    }
    missing = wanted - present
    if not missing:
        return set()
    proven = {
        str(value)
        for value in AuditLog.objects.filter(
            makerspace_id=makerspace_id,
            action=CLEANUP_ACTION,
            meta__evidence_id__in=[int(value) for value in missing if value.isdigit()],
        ).values_list("meta__evidence_id", flat=True)
    }
    unproven = missing - proven
    if unproven:
        raise ExportIntegrityError(
            "AuditLog targets missing EvidencePhoto rows without a cleanup record: "
            f"{sorted(unproven)[:5]}."
        )
    return proven
