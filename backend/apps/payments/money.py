"""Converting a ledger amount into the integer a provider expects.

`Payment.amount` is a Decimal in MAJOR units. Both vendors take the currency's smallest
unit as an int, and that unit is not always a hundredth: a yen has no subunit and a
Kuwaiti dinar has a thousandth. Multiplying everything by 100 charged a JPY member 100x the
debt and refunded a KWD member a tenth of it. The exponent table is ISO 4217's, matching
Stripe's published zero-decimal and three-decimal lists.
"""

from decimal import ROUND_HALF_UP, Decimal

ZERO_DECIMAL = frozenset(
    {
        "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
        "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
    }
)
THREE_DECIMAL = frozenset({"bhd", "jod", "kwd", "omr", "tnd"})


def minor_unit_exponent(currency):
    code = (currency or "").lower()
    if code in ZERO_DECIMAL:
        return 0
    if code in THREE_DECIMAL:
        return 3
    return 2


def to_minor_units(amount, currency):
    """Integer minor units, rounded half-up. Never a float."""
    scale = Decimal(10) ** minor_unit_exponent(currency)
    return int((Decimal(amount) * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
