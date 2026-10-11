from decimal import Decimal

from apps.operations.org_report_scope import EXCLUDED_ORGANIZATION_REPORT_KEYS
from apps.operations.org_report_strategies import STRATEGIES
from apps.operations.org_report_aggregate import aggregate_rows
from apps.operations.report_registry import REPORT_REGISTRY


def test_registry_has_a_strategy_or_explicit_exclusion_for_every_report():
    assert set(STRATEGIES) == set(REPORT_REGISTRY) - EXCLUDED_ORGANIZATION_REPORT_KEYS
    assert 'payment-cash-book' in STRATEGIES
    assert STRATEGIES['payment-cash-book'].grouping_keys == ('currency', 'method')
    assert set(STRATEGIES['payment-cash-book'].total_fields) == set(REPORT_REGISTRY['payment-cash-book'].fields)


def test_cash_book_totals_preserve_currency_method_and_decimal_precision():
    def row(currency, method, collected, refunded):
        return dict(currency=currency, method=method, collected_amount=Decimal(collected),
                    refunded_amount=Decimal(refunded), net_amount=Decimal(collected) - Decimal(refunded))
    rows = [(1, [row('usd', 'cash', '10.10', '1.05'), row('inr', 'cash', '20.00', '0')]),
            (2, [row('usd', 'cash', '5.05', '0'), row('usd', 'upi', '8.00', '2.00')])]
    assert aggregate_rows('payment-cash-book', rows, limit=100) == [
        row('inr', 'cash', '20.00', '0'), row('usd', 'cash', '15.15', '1.05'), row('usd', 'upi', '8.00', '2.00'),
    ]
