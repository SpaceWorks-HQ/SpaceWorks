"""Raw reversal deltas for retained-main foreign-key projection."""

from apps.backup.main_projection_registry import (
    BoundaryDisposition,
    boundary_queryset,
    boundary_rules,
    table_rules,
)
from apps.backup.raw_projection import fixture_payload, no_decrypt_guard, raw_records


def boundary_deltas(makerspace_id):
    """Serialize every declared retained-row boundary preimage into its slice."""
    result = []
    seen_dropped_rows = set()
    with no_decrypt_guard():
        for rule in boundary_rules(table_rules()):
            queryset = boundary_queryset(
                rule, "default", (makerspace_id,)
            ).order_by(rule.source_model._meta.pk.name)
            for record in raw_records(queryset, rule.source_model):
                fixture = fixture_payload(rule.source_model, (record,))[0]
                entry = {
                    "model": rule.source_model._meta.label,
                    "row_pk": fixture["pk"],
                    "field": rule.field.name,
                    "disposition": rule.disposition,
                }
                if rule.disposition == BoundaryDisposition.DROP_ROW_TO_SLICE:
                    identity = (entry["model"], str(entry["row_pk"]))
                    if identity in seen_dropped_rows:
                        continue
                    seen_dropped_rows.add(identity)
                    entry["row_preimage"] = fixture
                else:
                    entry["field_preimage"] = fixture["fields"][rule.field.name]
                result.append(entry)
    return result
