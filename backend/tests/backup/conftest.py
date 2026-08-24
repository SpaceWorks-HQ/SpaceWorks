import json

import pytest

from apps.backup import producer_capability


@pytest.fixture(autouse=True)
def installed_producer_capability(
    tmp_path_factory, monkeypatch, settings, disable_axes_by_default
):
    """Give existing backup tests the production precondition they do not exercise."""
    capability_root = tmp_path_factory.mktemp("producer-capability")
    scripts = capability_root / "scripts"
    scripts.mkdir()
    for name in producer_capability.PRIVILEGED_SCRIPT_NAMES:
        (scripts / name).write_bytes(f"installed:{name}\n".encode("ascii"))
    entrypoint = capability_root / "spaceworks_entrypoint.py"
    entrypoint.write_bytes(b"installed common entrypoint\n")
    migrations = capability_root / "installed-apps" / "backup" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "0001_initial.py").write_bytes(b"installed migration\n")
    marker = capability_root / "producer-capability.json"
    payload = producer_capability.capability_marker_payload(
        script_paths={
            name: scripts / name
            for name in producer_capability.PRIVILEGED_SCRIPT_NAMES
        },
        entrypoint_path=entrypoint,
        verification_public_key=settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY,
        migrations_root=migrations.parents[1],
    )
    marker.write_text(json.dumps(payload), encoding="utf-8")
    marker.chmod(0o444)
    settings.BACKUP_PRODUCER_CAPABILITY_MARKER_PATH = str(marker)
    settings.BACKUP_PRODUCER_PRIVILEGED_SCRIPTS_DIR = str(scripts)
    settings.BACKUP_PRODUCER_ENTRYPOINT_PATH = str(entrypoint)
    settings.BACKUP_PRODUCER_MIGRATIONS_DIR = str(migrations.parents[1])
    monkeypatch.setattr(
        producer_capability, "_assert_trusted_file", lambda _path: None
    )
    return {
        "marker": marker,
        "payload": payload,
        "scripts": scripts,
        "entrypoint": entrypoint,
        "migrations": migrations.parents[1],
    }
