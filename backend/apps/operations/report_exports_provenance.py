"""Provenance stamped onto every report export (CSV header row, XLSX sheet).

One value per FILE, not per row: who generated it, when, for which makerspace, from which
report definition/version and with which filters. It rides as a leading `#` line in CSV
and as a second `Provenance` sheet in XLSX, so the data columns stay exactly the fields
the report registry declares.
"""

import json
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

LEDGER_REPORT_KEY = "ledger"
LEDGER_REPORT_VERSION = 1


@dataclass(frozen=True)
class ExportProvenance:
    report_key: str
    report_version: int
    makerspace_id: int | None
    generated_by: str
    filters: dict
    generated_at: datetime

    def items(self):
        return (
            ("generated_at", self.generated_at.isoformat()),
            ("generated_by", self.generated_by),
            ("makerspace_id", "all" if self.makerspace_id is None else str(self.makerspace_id)),
            ("report_key", self.report_key),
            ("report_version", str(self.report_version)),
            ("filters", json.dumps(self.filters, sort_keys=True, separators=(",", ":"), default=str)),
        )

    def header_line(self):
        return "# " + " ".join(f"{key}={value}" for key, value in self.items())


def build_provenance(report_key, *, version, makerspace_id, generated_by, filters=None, now=None):
    return ExportProvenance(
        report_key=report_key,
        report_version=int(version),
        makerspace_id=makerspace_id,
        generated_by=generated_by,
        filters=dict(filters or {}),
        generated_at=now or timezone.now(),
    )


def actor_label(user):
    username = getattr(user, "username", "") if getattr(user, "is_authenticated", False) else ""
    return username or "system"


def export_filters(*, date_range=None, report_filters=None, grain=None, extra=None):
    """Flatten the export inputs into the JSON the provenance row carries; drop empties."""
    start, end = date_range or (None, None)
    filters = {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "grain": grain,
        **(report_filters or {}),
        **(extra or {}),
    }
    return {key: value for key, value in filters.items() if value not in (None, "")}
