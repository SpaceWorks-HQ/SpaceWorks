"""Pre-destructive validation of tenant-owned age identity mounts."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import subprocess

from django.core.exceptions import ValidationError

from apps.backup.recipients import canonical_recipient, fingerprint_for

from .tenant_dump_errors import TenantDumpTargetError


FORBIDDEN_IDENTITY_ENV_NAMES = frozenset(
    {
        "AGE_IDENTITY",
        "AGE_IDENTITIES",
        "TENANT_AGE_IDENTITY",
        "TENANT_DUMP_AGE_IDENTITY",
    }
)

# Section 2.4 forbids identities as command arguments outright, so the option NAME is refused
# even when it carries only a path: argv is world-readable through /proc, and the flag alone
# tells an unprivileged local process which mount to race for.
FORBIDDEN_IDENTITY_ARGV_OPTIONS = frozenset(
    {
        "--identity",
        "--identities",
        "--identity-file",
        "--age-identity",
        "--age-identities",
        "--tenant-identity",
        "--tenant-dump-identity",
    }
)


@dataclass(frozen=True, repr=False)
class TargetTenantIdentity:
    """A validated mount plus its non-secret canonical public identity."""

    path: Path
    public_recipient: str
    fingerprint: str


def preflight_target_identities(
    identity_paths,
    frozen_tenant_dek_recipients,
    *,
    environ=None,
    command_argv=None,
    mountinfo_path="/proc/self/mountinfo",
):
    """Require an exact tenant-recipient set before target state can be changed."""
    _reject_environment_identity(environ if environ is not None else os.environ)
    paths = tuple(identity_paths)
    _reject_command_line_identity(command_argv or (), paths)
    if not paths:
        _refuse("No tenant identity file was supplied.", "no_identity")
    frozen = _validated_frozen_recipients(frozen_tenant_dek_recipients)
    if not frozen:
        _refuse(
            "The artifact has no verified tenant DEK recipient.",
            "no_verified_tenant_recipient",
        )

    identities = []
    seen_paths = set()
    seen_fingerprints = set()
    for raw_path in paths:
        path = _validated_identity_mount(raw_path, mountinfo_path=mountinfo_path)
        if path in seen_paths:
            _refuse("A tenant identity mount was supplied more than once.", "duplicate_identity")
        seen_paths.add(path)
        recipient = _derive_public_recipient(path)
        fingerprint = fingerprint_for(recipient)
        if fingerprint in seen_fingerprints:
            _refuse(
                "Two identity mounts resolve to the same tenant recipient.",
                "duplicate_identity",
            )
        seen_fingerprints.add(fingerprint)
        if frozen.get(fingerprint) != recipient:
            _refuse(
                "A supplied identity is not a frozen tenant DEK recipient.",
                "outer_platform_only_or_no_match",
            )
        identities.append(TargetTenantIdentity(path, recipient, fingerprint))

    if seen_fingerprints != set(frozen):
        _refuse(
            "The supplied tenant identity set does not match the frozen recipient set.",
            "recipient_set_mismatch",
        )
    return tuple(sorted(identities, key=lambda item: item.fingerprint))


def _validated_frozen_recipients(rows):
    result = {}
    try:
        for row in rows:
            recipient = canonical_recipient(row["public_recipient"])
            fingerprint = row["fingerprint"]
            if fingerprint != fingerprint_for(recipient) or fingerprint in result:
                raise ValueError
            result[fingerprint] = recipient
    except (KeyError, TypeError, ValueError, ValidationError):
        _refuse("The frozen tenant DEK recipient set is invalid.", "invalid_frozen_recipients")
    return result


def _validated_identity_mount(raw_path, *, mountinfo_path):
    if not isinstance(raw_path, (str, os.PathLike)):
        _refuse("Tenant identities must be supplied as mounted file paths.", "inline_identity")
    raw_text = os.fspath(raw_path)
    if raw_text.startswith("AGE-SECRET-KEY-") or "\nAGE-SECRET-KEY-" in raw_text:
        _refuse("Inline tenant identities are forbidden.", "inline_identity")
    path = Path(raw_text)
    if not path.is_absolute():
        _refuse("Tenant identity mounts must use absolute paths.", "identity_path_relative")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError:
        _refuse("A tenant identity mount is unavailable.", "identity_path_unavailable")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        _refuse("A tenant identity mount must be a regular file.", "identity_path_type")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        _refuse("A tenant identity mount must have mode 0600.", "identity_path_mode")
    if not _is_read_only_host_mount(resolved, mountinfo_path=mountinfo_path):
        _refuse(
            "A tenant identity file must be supplied by a read-only host mount.",
            "identity_mount_writable",
        )
    return resolved


def _is_read_only_host_mount(path, *, mountinfo_path):
    """Match the deepest non-root mount and require its VFS mount option to be ro."""
    try:
        lines = Path(mountinfo_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    candidates = []
    for line in lines:
        fields = line.split()
        try:
            separator = fields.index("-")
            mount_point = Path(_unescape_mountinfo(fields[4])).resolve(strict=False)
            options = frozenset(fields[5].split(","))
        except (IndexError, ValueError, OSError):
            continue
        try:
            path.relative_to(mount_point)
        except ValueError:
            continue
        candidates.append((len(mount_point.parts), mount_point, options, separator))
    if not candidates:
        return False
    _depth, mount_point, options, _separator = max(candidates, key=lambda item: item[0])
    return mount_point != Path("/") and "ro" in options


def _unescape_mountinfo(value):
    for escaped, decoded in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(escaped, decoded)
    return value


def _derive_public_recipient(path):
    try:
        with path.open("rb", buffering=0) as identity:
            result = subprocess.run(
                ["age-keygen", "-y"],
                stdin=identity,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=_public_tool_environment(),
                check=True,
            )
        recipient = canonical_recipient(result.stdout.decode("ascii").strip())
    except (OSError, UnicodeError, subprocess.CalledProcessError, ValidationError):
        _refuse("A tenant identity file is invalid.", "identity_invalid")
    return recipient


def _public_tool_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "TZ"}
    }


def _reject_environment_identity(environ):
    found = [name for name in FORBIDDEN_IDENTITY_ENV_NAMES if environ.get(name)]
    inline = any(
        isinstance(value, str) and "AGE-SECRET-KEY-" in value
        for value in environ.values()
    )
    if found or inline:
        _refuse(
            "Tenant identities may not be supplied through the environment.",
            "identity_environment",
        )


def _reject_command_line_identity(argv, identity_paths):
    """Refuse an identity in argv whether it is inline secret text or a mount path."""
    mounts = {str(path) for path in identity_paths}
    for value in argv:
        if not isinstance(value, str):
            continue
        if "AGE-SECRET-KEY-" in value:
            _refuse(
                "Inline tenant identities are forbidden in command arguments.",
                "inline_identity",
            )
        if value.split("=", 1)[0] in FORBIDDEN_IDENTITY_ARGV_OPTIONS or value in mounts:
            _refuse(
                "Tenant identities may not be named in command arguments.",
                "inline_identity",
            )


def _refuse(message, code):
    raise TenantDumpTargetError(message, code=code)
