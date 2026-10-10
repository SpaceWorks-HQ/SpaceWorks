"""Loan terms travel as tenant policy, bounded by target-owned feature gates."""

from .tenant_dump_types import AuthorityDisposition, authority


def _fields(label, names, reason):
    return {(label, name): reason for name in names.split()}


LOAN_AUTHORITY_FIELDS = {
    **_fields(
        "makerspaces.MakerspaceLoanPolicy",
        "makerspace default_loan_days loan_renewal_mode loan_max_renewals "
        "loan_renewal_days loan_max_active loan_max_items loan_reminder_offsets_hours "
        "loan_escalate_overdue_days",
        "Tenant loan terms and reminder offsets travel; target-owned modules, "
        "features and recipient rules still bound borrowing and disclosure.",
    ),
    **_fields(
        "makerspaces.MembershipPlan", "loan_max_active loan_max_items",
        "Plan borrowing ceilings travel with tenant plans, bounded by the target loans.limits feature.",
    ),
    **_fields(
        "inventory.Category", "loan_days max_renewals",
        "Category loan terms travel; renewal authority still requires the target feature and borrower checks.",
    ),
    **_fields(
        "inventory.InventoryProduct", "loan_days max_renewals",
        "Product loan terms travel; renewal authority still requires the target feature and borrower checks.",
    ),
    **_fields(
        "hardware_requests.HardwareRequest", "renewal_count",
        "Consumed renewal slots are contractual history; importing must not replenish them.",
    ),
}

LOAN_AUTHORITY_ENTRIES = tuple(
    (edge, authority(AuthorityDisposition.PRESERVE, reason))
    for edge, reason in LOAN_AUTHORITY_FIELDS.items()
)
