"""Canonical, non-disclosing digest for the frozen global-user closure."""

import hashlib
import struct

from apps.backup.recipient_selection import BackupBuildError


USER_CLOSURE_ENCODING_VERSION = 1
DISPOSITIONS = ("included", "stubbed", "refused")
_DOMAIN = b"spaceworks-user-closure-ledger\x00"


def canonical_user_pk(value):
    if isinstance(value, bool):
        raise BackupBuildError("A user-closure identity is invalid.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise BackupBuildError("A user-closure identity is invalid.") from exc
    if number < 1 or str(number) != str(value):
        raise BackupBuildError("A user-closure identity is not canonical.")
    return str(number)


def canonical_user_closure(entries, *, encoding_version=USER_CLOSURE_ENCODING_VERSION):
    if type(encoding_version) is not int or not 0 <= encoding_version <= 0xFFFF:
        raise BackupBuildError("The user-closure encoding version is invalid.")
    grouped = {disposition: [] for disposition in DISPOSITIONS}
    identities = {}
    for entry in entries:
        try:
            disposition, source_pk, reason_code = entry
        except (TypeError, ValueError) as exc:
            raise BackupBuildError("A user-closure tuple is malformed.") from exc
        if disposition not in grouped:
            raise BackupBuildError("A user-closure disposition is invalid.")
        source_pk = canonical_user_pk(source_pk)
        if not isinstance(reason_code, str) or not reason_code or len(reason_code) > 128:
            raise BackupBuildError("A user-closure reason code is invalid.")
        identity = (disposition, reason_code)
        if source_pk in identities and identities[source_pk] != identity:
            raise BackupBuildError("A user has conflicting closure dispositions.")
        identities[source_pk] = identity
        encoded = b"".join((_frame(source_pk.encode("ascii")), _frame(reason_code.encode())))
        if encoded not in grouped[disposition]:
            grouped[disposition].append(encoded)

    payload = bytearray(_DOMAIN)
    payload.extend(struct.pack(">H", encoding_version))
    for disposition in DISPOSITIONS:
        payload.extend(_frame(disposition.encode("ascii")))
        values = sorted(grouped[disposition])
        payload.extend(struct.pack(">Q", len(values)))
        for value in values:
            payload.extend(_frame(value))
    return bytes(payload)


def user_closure_digest(entries, *, encoding_version=USER_CLOSURE_ENCODING_VERSION):
    return hashlib.sha256(
        canonical_user_closure(entries, encoding_version=encoding_version)
    ).hexdigest()


def _frame(value):
    return struct.pack(">Q", len(value)) + value
