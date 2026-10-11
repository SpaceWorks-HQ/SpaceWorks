"""Canonical composition point for every report definition."""

from apps.operations.report_definitions_audit import AUDIT_REPORT_DEFINITIONS
from apps.operations.report_definitions_coverage import COVERAGE_REPORT_DEFINITIONS
from apps.operations.report_definitions_existing import EXISTING_REPORT_DEFINITIONS
from apps.operations.report_definitions_membership import MEMBERSHIP_REPORT_DEFINITIONS
from apps.operations.report_types import (
    ReportDefinition,
    ReportNotExportable,
    ReportNotFound,
    ReportResult,
)


REPORT_DEFINITIONS = (
    *EXISTING_REPORT_DEFINITIONS, *COVERAGE_REPORT_DEFINITIONS, *AUDIT_REPORT_DEFINITIONS,
    *MEMBERSHIP_REPORT_DEFINITIONS,
)
REPORT_REGISTRY = {definition.key: definition for definition in REPORT_DEFINITIONS}
REPORT_KEYS = [definition.key for definition in REPORT_DEFINITIONS]
# The only definitions any deployment-wide (all-makerspaces) surface may enumerate or run.
DEPLOYMENT_AGGREGATE_REPORT_DEFINITIONS = tuple(
    definition for definition in REPORT_DEFINITIONS if definition.deployment_aggregate
)
DEPLOYMENT_AGGREGATE_REPORT_KEYS = [
    definition.key for definition in DEPLOYMENT_AGGREGATE_REPORT_DEFINITIONS
]


def report_definition(report_key, *, for_export=False, deployment_aggregate=False):
    definition = REPORT_REGISTRY.get(report_key)
    if definition is None or (deployment_aggregate and not definition.deployment_aggregate):
        raise ReportNotFound()
    if for_export and not definition.exportable:
        raise ReportNotExportable()
    return definition


__all__ = [
    "DEPLOYMENT_AGGREGATE_REPORT_DEFINITIONS", "DEPLOYMENT_AGGREGATE_REPORT_KEYS",
    "REPORT_DEFINITIONS", "REPORT_KEYS", "REPORT_REGISTRY", "ReportDefinition",
    "ReportNotExportable", "ReportNotFound", "ReportResult", "report_definition",
]
