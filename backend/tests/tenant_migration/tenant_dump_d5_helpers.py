from pathlib import Path

from apps.backup.digests import sha256_bytes, sha256_file
from apps.backup.recipients import fingerprint_for
from apps.backup.recipients_bech32 import convert_bits, encode
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.tenant_dump_envelope import TENANT_DEKS_MEMBER
from apps.tenant_migration.tenant_dump_lineage import FORMAT
from apps.tenant_migration.tenant_dump_target_deks import (
    TARGET_IMPORT_RECOVERY_MODE,
    TargetInstallSafety,
)
from apps.tenant_migration.tenant_dump_target_identities import TargetTenantIdentity


def age_recipient(seed):
    return encode("age", convert_bits(bytes([seed]) * 32, 8, 5, pad=True))


def frozen_recipient(seed):
    recipient = age_recipient(seed)
    return {
        "public_recipient": recipient,
        "fingerprint": fingerprint_for(recipient),
    }


def target_identity(path, seed):
    recipient = age_recipient(seed)
    return TargetTenantIdentity(
        path=Path(path),
        public_recipient=recipient,
        fingerprint=fingerprint_for(recipient),
    )


def key_inventory(makerspace_id, *, versions=((3, "rotated"), (7, "active"))):
    return [
        {
            "source_key_row_id": 100 + version,
            "makerspace_id": makerspace_id,
            "version": version,
            "status": status,
            "source_broker_backend": "local",
            "source_broker_key_id": "source-broker",
            "source_wrapped_dek_sha256": sha256_bytes(
                f"source-wrapped-{version}".encode()
            ),
        }
        for version, status in versions
    ]


def target_manifest(makerspace_id, *, recipient_seeds=(11,), inventory=None):
    return {
        "format": FORMAT,
        "source_pii_mode": "encrypted",
        "source": {
            "makerspace_id": makerspace_id,
            "tenant_recipients": [
                frozen_recipient(seed) for seed in recipient_seeds
            ],
        },
        "encryption": {
            "retained_key_inventory": (
                key_inventory(makerspace_id) if inventory is None else inventory
            ),
            "tenant_dek_envelope": {},
        },
    }


def envelope_manifest(tmp_path, makerspace_id):
    path = tmp_path / "tenant-deks.age"
    path.write_bytes(b"opaque tenant-only age ciphertext")
    manifest = target_manifest(makerspace_id)
    manifest["encryption"]["tenant_dek_envelope"] = {
        "path": TENANT_DEKS_MEMBER,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    return manifest, path


def safe_target():
    return TargetInstallSafety(
        non_routable=True,
        recovery_mode=TARGET_IMPORT_RECOVERY_MODE,
    )


def importing_space(slug):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        lifecycle_state=Makerspace.LifecycleState.IMPORTING,
        superadmin_access_enabled=True,
    )


def write_read_only_mountinfo(tmp_path, mounted_path, *, read_only=True):
    options = "ro,relatime" if read_only else "rw,relatime"
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        f"36 25 0:32 / {mounted_path} {options} - tmpfs tmpfs {options}\n",
        encoding="utf-8",
    )
    return mountinfo
