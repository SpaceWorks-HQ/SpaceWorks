"""Loan-period inheritance. Inventory Availability still owns stock quantities."""

from .models_loan_policy import MakerspaceLoanPolicy


def loan_days(makerspace, products=(), *, policy=None):
    policy = policy or MakerspaceLoanPolicy.for_makerspace(makerspace)
    periods = [
        product.loan_days or (product.category.loan_days if product.category_id else None)
        or policy.default_loan_days
        for product in products
    ]
    # A bundle comes back together, at the shortest period of its contents.
    return min(periods, default=policy.default_loan_days)


def renewal_cap(policy, products):
    caps = []
    for product in products:
        cap = product.max_renewals
        if cap is None and product.category_id:
            cap = product.category.max_renewals
        caps.append(policy.loan_max_renewals if cap is None else cap)
    return min(caps, default=policy.loan_max_renewals)
