"""E.164 normalisation for phone as a login identity.

Deliberately strict and dependency-free: the number must be given in full
international form (``+<country><subscriber>``). The alternative -- guessing a
country for a bare local number -- is what makes phone identity ambiguous, and an
ambiguous identity is a login that hands one person's account to another. The
`phonenumbers` library would buy prettier input handling at the cost of a
dependency and a per-region default that would still have to be guessed.

Only separators humans actually type are stripped. Anything else is rejected
rather than silently cleaned, because a "cleaned" number that differs from what
the user believes they typed is a support ticket at best.
"""

import re

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_STRIPPABLE = re.compile(r"[\s\-().]")

MESSAGE = (
    "Enter the number in full international format, starting with + and the "
    "country code (for example +14155552671)."
)


class InvalidPhoneNumber(ValueError):
    pass


def normalize_e164(raw):
    """Return a canonical E.164 string, or raise InvalidPhoneNumber.

    Canonicalisation matters for uniqueness: '+1 (415) 555-2671' and '+14155552671'
    are the same identity and must collide on the unique index, not sit beside each
    other as two accounts.
    """
    if raw is None:
        raise InvalidPhoneNumber(MESSAGE)
    value = _STRIPPABLE.sub("", str(raw).strip())
    # A leading 00 is the other spelling of + that people genuinely type.
    if value.startswith("00"):
        value = "+" + value[2:]
    if not E164_RE.match(value):
        raise InvalidPhoneNumber(MESSAGE)
    return value


def normalize_or_none(raw):
    """Best-effort variant for lookups, where a bad number simply matches nothing."""
    try:
        return normalize_e164(raw)
    except InvalidPhoneNumber:
        return None
