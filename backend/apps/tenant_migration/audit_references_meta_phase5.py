"""Audit meta id edges added by forward plan phase 5 (member ID cards, certification gating)."""
from .audit_references_targets import AuditReference, AuditReferenceDisposition

R = AuditReferenceDisposition.REMAP


def _reference(disposition, model, *edges):
    return {edge: AuditReference(disposition, model) for edge in edges}


PHASE5_AUDIT_EDGES = {}
# Member ID cards (forward plan phase 5): card ids remap to the exported MemberCard row;
# the scan-time QR id remaps like every other QR reference.
PHASE5_AUDIT_EDGES.update(
    _reference(
        R, "makerspaces.MemberCard",
        ("member_card.created", "card_id"), ("member_card.issued", "card_id"),
        ("member_card.reissued", "card_id"), ("member_card.revoked", "card_id"),
        ("member_card.printed", "card_id"), ("member_card.name_updated", "card_id"),
        ("member_card.photo_updated", "card_id"), ("member_card.photo_removed", "card_id"),
    )
)
PHASE5_AUDIT_EDGES.update(_reference(R, "boxes.QrCode", ("member_card.scanned", "qr_id")))
# Certification gating (phase 5, machines lane).
PHASE5_AUDIT_EDGES.update(
    _reference(
        R, "machines.CertificationType",
        ("certification.granted", "certification_type_id"),
        ("certification.revoked", "certification_type_id"),
        ("certification.override", "certification_type_id"),
    )
)
PHASE5_AUDIT_EDGES.update(
    _reference(
        R, "makerspaces.MakerspaceMembership",
        ("certification.granted", "membership_id"), ("certification.revoked", "membership_id"),
    )
)
PHASE5_AUDIT_EDGES.update(
    _reference(R, "machines.MachineType", ("certification_type.created", "machine_type_id"))
)
