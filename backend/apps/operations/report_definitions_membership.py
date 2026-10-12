from apps.accounts import rbac
from apps.operations.report_types import ReportDefinition
from apps.operations.reports_retention import FIELDS as RETENTION_FIELDS
from apps.operations.reports_membership_revenue import FIELDS as REVENUE_FIELDS

MEMBERSHIP_REPORT_DEFINITIONS = (
    ReportDefinition("member-retention", "apps.operations.reports_retention.build_member_retention",
                     RETENTION_FIELDS, ("membership",), title="Member retention and cohorts"),
    ReportDefinition("membership-revenue", "apps.operations.reports_membership_revenue.build_membership_revenue",
                     REVENUE_FIELDS, ("membership",), required_action=rbac.Action.VIEW_FINANCE,
                     title="Membership MRR / ARR", grains=("month",)),
)
