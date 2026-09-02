from dataclasses import dataclass

from django.core import checks

from apps.makerspaces.module_registry import MODULE_KEYS
from apps.operations.report_registry import REPORT_REGISTRY


@dataclass(frozen=True)
class ModuleReportCoverage:
    kind: str
    reports: tuple[str, ...]


REPORT_MODULE_COVERAGE = {
    "public_inventory": ModuleReportCoverage("composite", ("inventory-control",)),
    "request_workflow": ModuleReportCoverage("substantive", ("loan-throughput",)),
    "staff_admin": ModuleReportCoverage("health_row", ("module-operational-health",)),
    "guest_handover": ModuleReportCoverage("composite", ("loan-throughput",)),
    "scanner": ModuleReportCoverage("substantive", ("qr-scans", "module-operational-health")),
    "printing": ModuleReportCoverage("substantive", ("printer-service",)),
    "telegram": ModuleReportCoverage("composite", ("communications-health",)),
    "evidence_uploads": ModuleReportCoverage("substantive", ("evidence-compliance",)),
    "qr_management": ModuleReportCoverage("composite", ("inventory-control",)),
    "bulk_import": ModuleReportCoverage("substantive", ("import-quality",)),
    "containers": ModuleReportCoverage("composite", ("inventory-control",)),
    "stock_transfers": ModuleReportCoverage("composite", ("inventory-control",)),
    "stocktake": ModuleReportCoverage("composite", ("inventory-control",)),
    "reports": ModuleReportCoverage("health_row", ("module-operational-health",)),
    "qr_print_batches": ModuleReportCoverage("composite", ("inventory-control",)),
    "asset_units": ModuleReportCoverage("composite", ("inventory-control",)),
    "procurement": ModuleReportCoverage("substantive", ("procurement-performance",)),
    "machines": ModuleReportCoverage("substantive", ("machine-usage", "module-operational-health")),
    "machine_service": ModuleReportCoverage("substantive", ("machine-service",)),
    "events": ModuleReportCoverage("substantive", ("event-attendance",)),
    "bookings": ModuleReportCoverage("substantive", ("booking-utilization",)),
    "maintenance": ModuleReportCoverage("substantive", ("maintenance-activity",)),
    "membership": ModuleReportCoverage("substantive", ("member-activity", "community-engagement")),
    "notifications": ModuleReportCoverage("composite", ("communications-health",)),
    "email": ModuleReportCoverage("composite", ("communications-health",)),
    "slack": ModuleReportCoverage("composite", ("communications-health",)),
    "mattermost": ModuleReportCoverage("composite", ("communications-health",)),
    "discord": ModuleReportCoverage("composite", ("communications-health",)),
    "payments": ModuleReportCoverage("substantive", ("payment-reconciliation",)),
    "member_accounts": ModuleReportCoverage("composite", ("community-engagement",)),
    "mobile": ModuleReportCoverage("composite", ("community-engagement",)),
    "updates": ModuleReportCoverage("health_row", ("module-operational-health",)),
}


@checks.register(checks.Tags.models)
def check_report_module_coverage(app_configs=None, **kwargs):
    errors = []
    missing = MODULE_KEYS - REPORT_MODULE_COVERAGE.keys()
    extra = REPORT_MODULE_COVERAGE.keys() - MODULE_KEYS
    if missing or extra:
        errors.append(checks.Error(
            f"Report coverage differs from module registry; missing={sorted(missing)}, extra={sorted(extra)}.",
            id="operations.E001",
        ))
    for module_key, coverage in REPORT_MODULE_COVERAGE.items():
        for report_key in coverage.reports:
            definition = REPORT_REGISTRY.get(report_key)
            if definition is None:
                errors.append(checks.Error(
                    f"Module {module_key!r} references unknown report {report_key!r}.",
                    id="operations.E002",
                ))
            elif coverage.kind == "composite" and module_key not in definition.section_modules:
                errors.append(checks.Error(
                    f"Composite report {report_key!r} omits the {module_key!r} section gate.",
                    id="operations.E003",
                ))
    for definition in REPORT_REGISTRY.values():
        unknown = (set(definition.required_modules) | set(definition.section_modules)) - MODULE_KEYS
        if unknown:
            errors.append(checks.Error(
                f"Report {definition.key!r} references unknown modules {sorted(unknown)}.",
                id="operations.E004",
            ))
    return errors
