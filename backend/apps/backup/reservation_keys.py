"""PostgreSQL-exact, non-ambiguous Lane E reservation key framing."""

from dataclasses import dataclass
import hashlib
import secrets


KEY_VERSION = b"reservation-key-v1"
COMMITMENT_DOMAIN = b"spaceworks-b1-reservation-v1"
SALT_BYTES = 32


class ReservationKeyError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalComponent:
    """One PostgreSQL-evaluated unique-index component."""

    type_identity: str
    value: bytes | None

    def __post_init__(self):
        if not self.type_identity or "\x00" in self.type_identity:
            raise ReservationKeyError("A stable PostgreSQL type identity is required.")
        if self.value is not None and not isinstance(self.value, bytes):
            raise ReservationKeyError("Canonical component values must be bytea.")


def fresh_run_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def reservation_key_v1(
    constraint_identity: str,
    components: tuple[CanonicalComponent, ...] | list[CanonicalComponent],
    *,
    nulls_not_distinct: bool,
) -> bytes | None:
    """Frame one ordered composite key; never concatenate textual values.

    A default NULLS DISTINCT unique rule reserves nothing for a row containing
    any null key component.  Under NULLS NOT DISTINCT, the null marker is part
    of the key and can therefore collide exactly as PostgreSQL would.
    """

    if not _is_digest(constraint_identity):
        raise ReservationKeyError("The constraint identity must be a SHA-256 digest.")
    ordered = tuple(components)
    if not ordered:
        raise ReservationKeyError("A reservation key needs at least one component.")
    if not nulls_not_distinct and any(item.value is None for item in ordered):
        return None
    result = bytearray()
    result += _frame(KEY_VERSION)
    result += _frame(bytes.fromhex(constraint_identity))
    result += len(ordered).to_bytes(4, "big")
    for item in ordered:
        result += _frame(item.type_identity.encode("utf-8"))
        if item.value is None:
            result += b"\x00"
        else:
            result += b"\x01" + _frame(item.value)
    return bytes(result)


def reservation_commitment(run_salt: bytes, framed_key: bytes) -> str:
    if not isinstance(run_salt, bytes) or len(run_salt) != SALT_BYTES:
        raise ReservationKeyError("A fresh 32-byte run salt is required.")
    if not isinstance(framed_key, bytes) or not framed_key:
        raise ReservationKeyError("A framed reservation key is required.")
    return hashlib.sha256(COMMITMENT_DOMAIN + run_salt + framed_key).hexdigest()


def _frame(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def _is_digest(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
