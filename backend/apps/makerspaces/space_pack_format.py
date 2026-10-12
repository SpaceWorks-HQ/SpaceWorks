"""Small checksummed JSON envelope; not a backup or portable tenant archive."""
import hashlib
import hmac
import json

from rest_framework.exceptions import APIException

FORMAT = "spaceworks-space-pack"
VERSION = 1
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000


class PackError(APIException):
    status_code = 400

    def __init__(self, code, detail):
        super().__init__({"code": code, "detail": detail}, code=code)


class PackConflict(PackError):
    status_code = 409


def canonical(value):
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        raise PackError("invalid_pack", "Use finite JSON values.")
    if len(data) > MAX_BYTES:
        raise PackError("pack_too_large", "A pack may contain at most 2 MiB of JSON.")
    return data


def seal(configuration):
    unsigned = {"format": FORMAT, "version": VERSION, "configuration": configuration}
    return {**unsigned, "checksum": hashlib.sha256(canonical(unsigned)).hexdigest()}


def open_pack(pack):
    if not isinstance(pack, dict) or set(pack) != {"format", "version", "configuration", "checksum"}:
        raise PackError("invalid_pack", "Use a space pack envelope with exactly four fields.")
    if pack["format"] != FORMAT or type(pack["version"]) is not int or pack["version"] != VERSION:
        raise PackError("unsupported_pack_version", "Only spaceworks-space-pack version 1 is supported.")
    checksum = pack["checksum"]
    unsigned = {key: pack[key] for key in ("format", "version", "configuration")}
    expected = hashlib.sha256(canonical(unsigned)).hexdigest()
    if (not isinstance(checksum, str) or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum)
            or not hmac.compare_digest(checksum, expected)):
        raise PackError("pack_checksum_mismatch", "The pack checksum does not match its contents.")
    return pack["configuration"]
