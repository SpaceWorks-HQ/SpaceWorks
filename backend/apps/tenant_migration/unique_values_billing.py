"""Refund receipt identity remaps; the billing policy is already tenant-scoped."""

from .unique_values_policy import REMAP, _policy

BILLING_UNIQUE_RULES = {
    ("payments.Refund", "field:amends"): _policy(
        REMAP, "Receipt corrections follow the imported refund identity without branching.",
    ),
}
