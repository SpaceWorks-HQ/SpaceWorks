"""Public borrowing terms reuse the actual loan policy, without stock/history."""

from apps.makerspaces.loan_policy import loan_days


def borrowing_terms(product, *, cache=None):
    from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
    from apps.payments.availability import charge_tracking_enabled
    from apps.payments.models import MakerspacePaymentSettings
    cache = {} if cache is None else cache
    if product.makerspace_id not in cache:
        space = product.makerspace
        cache[space.pk] = (space, MakerspaceLoanPolicy.for_makerspace(space),
                          MakerspacePaymentSettings.for_makerspace(space)
                          if charge_tracking_enabled(space, "loans") else None)
    space, policy, settings = cache[product.makerspace_id]
    days = loan_days(space, (product,), policy=policy)
    terms = [f"Loan period: {days} days."]
    if settings:
        amount = settings.loan_deposit_amount if settings.loan_deposit_mode == "fixed" else (
            product.deposit_amount if settings.loan_deposit_mode == "per_product" else None)
        if amount and amount > 0:
            basis = "per loan" if settings.loan_deposit_mode == "fixed" else "per item"
            terms.append(f"Deposit: {settings.default_currency.upper()} {amount:.2f} {basis}.")
    if product.borrowing_terms.strip():
        terms.append(product.borrowing_terms.strip())
    return " ".join(terms)
