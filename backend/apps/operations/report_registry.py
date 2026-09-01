"""Canonical composition point for every report definition."""

from apps.operations.report_definitions_coverage import COVERAGE_REPORT_DEFINITIONS
from apps.operations.report_definitions_existing import EXISTING_REPORT_DEFINITIONS
from apps.operations.report_types import (
    ReportDefinition,
    ReportNotExportable,
    ReportNotFound,
    ReportResult,
)


REPORT_DEFINITIONS = (*EXISTING_REPORT_DEFINITIONS, *COVERAGE_REPORT_DEFINITIONS)
REPORT_REGISTRY = {definition.key: definition for definition in REPORT_DEFINITIONS}
REPORT_KEYS = [definition.key for definition in REPORT_DEFINITIONS]


def report_definition(report_key, *, for_export=False):
    definition = REPORT_REGISTRY.get(report_key)
    if definition is None:
        raise ReportNotFound()
    if for_export and not definition.exportable:
        raise ReportNotExportable()
    return definition


__all__ = [
    "REPORT_DEFINITIONS", "REPORT_KEYS", "REPORT_REGISTRY", "ReportDefinition",
    "ReportNotExportable", "ReportNotFound", "ReportResult", "report_definition",
]
