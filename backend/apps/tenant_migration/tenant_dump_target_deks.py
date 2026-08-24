"""Key-free parent orchestration for target-side Lane D DEK installation."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from apps.backup.digests import sha256_file
from apps.encryption.cache import dek_cache_disabled
from apps.encryption.models import (
    MakerspaceEncryptionKey,
    PiiBlindIndex,
    SearchKeyGeneration,
)
from apps.events.models import EventRegistration

from .tenant_dump_envelope import TENANT_DEKS_MEMBER
from .tenant_dump_errors import TenantDumpTargetError
from .tenant_dump_target_identities import FORBIDDEN_IDENTITY_ENV_NAMES
from .tenant_dump_target_protocol import (
    encode_challenge_request,
    encode_install_request,
)


HELPER_MODULE = "apps.tenant_migration.tenant_dump_target_helper"
TARGET_IMPORT_RECOVERY_MODE = "target_import"
TARGET_HELPER_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class TargetInstallSafety:
    non_routable: bool
    recovery_mode: str


def install_target_deks(
    manifest,
    envelope_path,
    identities,
    *,
    safety,
):
    """Install exact carried DEKs while this parent remains plaintext-key free."""
    _require_safe_target(safety)
    source = manifest.get("source")
    encryption = manifest.get("encryption")
    if not isinstance(source, dict) or not isinstance(encryption, dict):
        _refuse("The Lane D encryption manifest is invalid.", "key_inventory")
    makerspace_id = source.get("makerspace_id")
    if manifest.get("source_pii_mode") != "encrypted":
        _refuse("A plaintext Lane D artifact has no DEKs to install.", "source_pii_mode")
    inventory = encryption.get("retained_key_inventory")
    envelope = encryption.get("tenant_dek_envelope")
    path = Path(envelope_path)
    _verify_envelope(path, envelope)
    assert_source_cryptographic_state_absent()
    request = encode_install_request(
        identities=identities,
        envelope_path=path,
        makerspace_id=makerspace_id,
        inventory=inventory,
    )
    with dek_cache_disabled():
        result = _run_helper(request)
    versions = result.get("installed_versions") if isinstance(result, dict) else None
    expected = sorted(item["version"] for item in inventory)
    if versions != expected:
        _refuse("The target DEK helper returned an invalid result.", "helper_result")
    return tuple(versions)


def decrypt_target_recipient_challenge(identity, encrypted_challenge):
    """Use the mounted identity in the bounded child; return only the public nonce."""
    request = encode_challenge_request(
        identity=identity,
        ciphertext=encrypted_challenge,
    )
    result = _run_helper(request)
    nonce = result.get("submitted_nonce") if isinstance(result, dict) else None
    if not isinstance(nonce, str) or not nonce:
        _refuse("The target recipient proof helper failed.", "challenge_decrypt")
    return nonce


def assert_source_cryptographic_state_absent():
    """Refuse source broker rows and source-derived search material after restore."""
    present = []
    if MakerspaceEncryptionKey.objects.exists():
        present.append("broker key rows")
    if PiiBlindIndex.objects.exists():
        present.append("blind indexes")
    if SearchKeyGeneration.objects.exists():
        present.append("search generations")
    if EventRegistration.objects.filter(email_exact_hash__isnull=False).exists():
        present.append("event blind indexes")
    if EventRegistration.objects.filter(email_hash_generation__isnull=False).exists():
        present.append("event search generations")
    if present:
        _refuse(
            "The restored Lane D database contains forbidden source cryptographic state: "
            + ", ".join(present)
            + ".",
            "source_crypto_state_present",
        )


def _require_safe_target(safety):
    if (
        type(safety) is not TargetInstallSafety
        or safety.non_routable is not True
        or safety.recovery_mode != TARGET_IMPORT_RECOVERY_MODE
    ):
        _refuse(
            "DEKs may be installed only in a non-routable target-import sibling.",
            "unsafe_target",
        )


def _verify_envelope(path, fact):
    if (
        not isinstance(fact, dict)
        or fact.get("path") != TENANT_DEKS_MEMBER
        or type(fact.get("size")) is not int
        or fact["size"] <= 0
        or not isinstance(fact.get("sha256"), str)
    ):
        _refuse("The tenant DEK envelope fact is invalid.", "key_envelope")
    try:
        size = path.stat().st_size
        digest = sha256_file(path)
    except OSError:
        _refuse("The tenant DEK envelope is unavailable.", "key_envelope")
    if size != fact["size"] or digest != fact["sha256"]:
        _refuse("The tenant DEK envelope does not match its manifest.", "key_envelope")


def _run_helper(request):
    process = None
    output = None
    failed = False
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", HELPER_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_helper_environment(),
            close_fds=True,
            start_new_session=True,
        )
        output, _unused = process.communicate(
            request, timeout=TARGET_HELPER_TIMEOUT_SECONDS
        )
        if process.returncode != 0 or not output:
            raise OSError
        result = json.loads(output)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except Exception:
        failed = True
    finally:
        request = None
        output = None
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()
    if failed:
        _refuse("The bounded target helper failed.", "target_helper_failed")


def _helper_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key not in FORBIDDEN_IDENTITY_ENV_NAMES
        and not (isinstance(value, str) and "AGE-SECRET-KEY-" in value)
    }


def _refuse(message, code):
    raise TenantDumpTargetError(message, code=code)
