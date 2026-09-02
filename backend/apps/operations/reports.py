from decimal import Decimal

from apps.operations.report_registry import (
    REPORT_KEYS,
    ReportResult,
    report_definition,
)
from apps.operations.reports_inventory import (
    _most_lent,
    _taken_items,
    _top_borrowers,
)
from apps.operations.reports_typed import typed_report_rows, typed_result_rows


DEFAULT_REPORT_LIMIT = 100
MAX_REPORT_LIMIT = 500


def report_data(
    report_key="summary", makerspace_id=None, *, limit=None, date_range=None,
    report_filters=None, grain="day",
):
    definition = report_definition(report_key)
    kwargs = dict(limit=_normalized_limit(limit), date_range=date_range, **(report_filters or {}))
    if definition.grains:
        kwargs["grain"] = grain
    result = definition.builder()(makerspace_id, **kwargs)
    if definition.summary:
        return result
    if not isinstance(result, ReportResult):
        return {"rows": result, "typed_rows": typed_report_rows(report_key, result)}
    rows = _matrix(result, json=True)
    return {
        "report_key": report_key,
        "rows": rows,
        "typed_rows": typed_result_rows(result, json_value),
        "meta": {"source": "live", "grain": grain, "rollup_through": None, **result.meta},
    }


def report_rows(
    report_key, makerspace_id=None, *, limit=None, date_range=None,
    report_filters=None, grain="day",
):
    definition = report_definition(report_key, for_export=True)
    kwargs = dict(limit=limit, date_range=date_range, **(report_filters or {}))
    if definition.grains:
        kwargs["grain"] = grain
    result = definition.builder()(makerspace_id, **kwargs)
    if isinstance(result, ReportResult):
        return _export_matrix(result, grain)
    return result


def required_modules(report_key):
    return report_definition(report_key).required_modules


def validate_report_key(report_key, *, for_export=False):
    return report_definition(report_key, for_export=for_export)


def _normalized_limit(limit):
    if limit is None:
        limit = DEFAULT_REPORT_LIMIT
    return max(0, min(int(limit), MAX_REPORT_LIMIT))


def _matrix(result, *, json):
    convert = json_value if json else (lambda value: value)
    return [
        list(result.field_order),
        *[
            [convert(record.get(field)) for field in result.field_order]
            for record in result.records
        ],
    ]


def _export_matrix(result, grain):
    # Provenance (source / grain / rollup_through) stays in the JSON response `meta` and is
    # deliberately NOT appended as export columns. It is one value per REPORT, not per row,
    # so appending it repeats itself on every line, and the export header of each report is
    # pinned to the fields the report registry declares -- the registry is the single source
    # of truth for a report's shape. Adding provenance to the file is a real product decision
    # about five already-shipped exports, and belongs to the owner rather than to this phase.
    return _matrix(result, json=False)


def json_value(value):
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), ".2f")
    return value
