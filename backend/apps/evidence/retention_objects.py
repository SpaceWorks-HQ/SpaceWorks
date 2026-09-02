from apps.evidence.models import EvidenceObjectRetentionState


def retention_object_states(makerspace):
    """Return state keyed by the immutable photo's final object key."""
    rows = EvidenceObjectRetentionState.objects.filter(
        evidence__makerspace=makerspace
    ).values(
        "evidence__object_key",
        "status",
        "object_expired_at",
        "expired_size_bytes",
    )
    return {
        row["evidence__object_key"]: {
            "status": row["status"],
            "object_expired_at": row["object_expired_at"],
            "expired_size_bytes": row["expired_size_bytes"],
        }
        for row in rows
    }
