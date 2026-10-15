"""Audited profile writes shared by staff settings and guided setup."""
from apps.audit import services as audit


def write_profile(actor, makerspace, values, payment=None):
    """Apply validated profile values with the caller holding the row locks."""
    changed = []
    for field in ("timezone", "country", "opening_hours"):
        if field in values and getattr(makerspace, field) != values[field]:
            setattr(makerspace, field, values[field])
            changed.append(field)
    if "default_currency" in values and payment.default_currency != values["default_currency"]:
        payment.default_currency = values["default_currency"]
        payment.save(update_fields=["default_currency"] if payment.pk else None)
        changed.append("default_currency")
    if changed:
        makerspace.save(update_fields=[field for field in changed if field != "default_currency"] + ["updated_at"])
        audit.record(actor, "makerspace.updated", makerspace=makerspace,
                     target=makerspace, meta={"fields": sorted(changed)})
