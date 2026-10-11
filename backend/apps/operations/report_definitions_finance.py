from apps.accounts import rbac
from apps.operations.report_types import ReportDefinition
from apps.operations.reports_finance import LEDGER_FIELDS, REVENUE_FIELDS, CASH_FIELDS
from apps.operations.reports_accounting import FIELDS as ACCOUNTING_FIELDS

FINANCE_REPORT_DEFINITIONS = (
    ReportDefinition("payments-ledger", "apps.operations.reports_finance.build_payments_ledger", LEDGER_FIELDS,
                     required_action=rbac.Action.VIEW_FINANCE, title="Payments ledger", deployment_aggregate=False),
    ReportDefinition("revenue-over-time", "apps.operations.reports_finance.build_revenue_over_time", REVENUE_FIELDS,
                     required_action=rbac.Action.VIEW_FINANCE, title="Collected, owed and refunded", chart_hint="line",
                     grains=("day", "week", "month")),
    ReportDefinition("cash-book", "apps.operations.reports_finance.build_cash_book", CASH_FIELDS,
                     required_action=rbac.Action.VIEW_FINANCE, title="Cash book by local date", grains=("day", "week", "month")),
    ReportDefinition("accounting-journal", "apps.operations.reports_accounting.build_accounting_journal", ACCOUNTING_FIELDS,
                     required_action=rbac.Action.VIEW_FINANCE, title="Accounting journal CSV", allowed_formats=("csv",),
                     deployment_aggregate=False),
)
