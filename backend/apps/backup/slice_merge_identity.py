"""Use an age identity only through stdin and zero the transient buffer."""

from pathlib import Path
import shutil
import subprocess

from apps.backup.recipients import canonical_recipient, fingerprint_for
from apps.backup.slice_merge_types import SliceMergeError


def read_identity(channel) -> bytearray:
    try:
        value = channel.read(65_537)
    except Exception:
        raise SliceMergeError("The tenant identity channel could not be read.") from None
    finally:
        try:
            channel.close()
        except Exception:
            pass
    if (
        not isinstance(value, (bytes, bytearray))
        or not value
        or len(value) > 65_536
    ):
        raise SliceMergeError("A tenant identity is required through the private input channel.")
    return bytearray(value)


def recipient_fingerprint(identity: bytearray) -> str:
    process = _start([_binary("age-keygen"), "-y"], stdout=subprocess.PIPE)
    public = _communicate(process, identity, capture=True)
    try:
        recipient = canonical_recipient(public.decode("ascii").strip())
    except Exception:
        raise SliceMergeError("The tenant identity is invalid or unsupported.") from None
    return fingerprint_for(recipient)


def decrypt_file(ciphertext, destination, identity: bytearray):
    command = [
        _binary("age"), "--decrypt", "--identity", "-", "--output",
        str(Path(destination)), str(Path(ciphertext)),
    ]
    process = _start(command, stdout=subprocess.DEVNULL)
    _communicate(process, identity)


def decrypt_bytes(ciphertext, identity: bytearray) -> bytearray:
    command = [_binary("age"), "--decrypt", "--identity", "-", str(ciphertext)]
    process = _start(command, stdout=subprocess.PIPE)
    return bytearray(_communicate(process, identity, capture=True))


def zeroize(value):
    if isinstance(value, bytearray):
        value[:] = b"\x00" * len(value)


def _start(command, *, stdout):
    try:
        return subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            env={},
        )
    except OSError:
        raise SliceMergeError("The tenant identity helper is unavailable.") from None


def _communicate(process, identity, *, capture=False):
    output = bytearray()
    try:
        process.stdin.write(identity)
        process.stdin.close()
        if capture:
            while chunk := process.stdout.read(64 * 1024):
                output.extend(chunk)
        return_code = process.wait()
    except Exception:
        process.kill()
        process.wait()
        zeroize(output)
        raise SliceMergeError("The tenant identity could not open this component.") from None
    if return_code:
        zeroize(output)
        raise SliceMergeError("The tenant identity could not open this component.")
    return output


def _binary(name):
    value = shutil.which(name)
    if not value:
        raise SliceMergeError("The tenant identity helper is unavailable.")
    return value
