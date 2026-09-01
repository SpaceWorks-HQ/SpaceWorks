"""HOST-ONLY: these assertions read files outside the backend Docker build context."""

from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest
import yaml

from apps.backup.topology import (
    TopologyConfigurationError,
    validate_scheduler_contract,
    validate_scheduler_environment,
)


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_ROLES = {
    "docker-compose.yml": {"backend": "backend", "worker": "worker", "beat": "beat", "migrate": "migrate"},
    "docker-compose.prod.yml": {"backend": "backend", "worker": "worker", "beat": "beat", "migrate": "migrate"},
    "docker-compose.cloud.yml": {"backend": "backend", "cron": "cron", "migrate": "migrate"},
}
PRODUCER_SERVICES = {
    "docker-compose.yml": {"backend", "worker"},
    "docker-compose.prod.yml": {"backend", "worker"},
    "docker-compose.cloud.yml": {"backend", "cron"},
}


def _compose(name):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_dockerfile_installs_the_single_common_entrypoint():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "groupadd --system --gid 10001 app" in dockerfile
    assert "--uid 10001 --gid app app" in dockerfile
    assert 'ENTRYPOINT ["python", "/app/scripts/spaceworks_entrypoint.py"]' in dockerfile
    assert dockerfile.count("ENTRYPOINT") == 1


def test_setup_installs_producer_capability_after_archive_key_creation():
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    helper = (ROOT / "scripts" / "setup-host-orchestration.sh").read_text(
        encoding="utf-8"
    )
    initializer = (ROOT / "scripts" / "init-host-orchestration.sh").read_text(
        encoding="utf-8"
    )

    assert setup.index("install_producer_capability") > setup.index(
        "BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY"
    )
    assert "/app/scripts/install_producer_capability.py" in helper
    assert "--scripts-dir /installed-scripts" in helper
    assert 'grep -E \'^BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY=\'' in helper
    installer = helper.split("install_producer_capability()", 1)[1].split(
        "configure_setup_stripe()", 1
    )[0]
    assert '-v "$ROOT:/repo:ro"' not in installer
    assert "install_producer_capability" in initializer


@pytest.mark.parametrize("name", COMPOSE_ROLES)
def test_producer_roles_see_marker_and_installed_scripts_read_only(name):
    services = _compose(name)["services"]
    for service_name in PRODUCER_SERVICES[name]:
        service = services[service_name]
        assert service["environment"]["BACKUP_PRODUCER_CAPABILITY_MARKER_PATH"] == (
            "/run/spaceworks-host/producer-capability.json"
        )
        assert any(
            str(volume).endswith(":/run/spaceworks-privileged-scripts:ro")
            for volume in service["volumes"]
        )


def test_bundled_host_scripts_route_management_commands_through_explicit_role():
    names = (
        "setup.sh", "setup.ps1", "scripts/import-backup.sh", "scripts/restore.sh",
        "scripts/update.sh", "scripts/update.ps1", "scripts/install-auto-update.sh",
        "scripts/install-auto-update.ps1",
    )
    for name in names:
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "exec -T backend python manage.py" not in source
        assert "backend python manage.py" not in source


@pytest.mark.parametrize("name", COMPOSE_ROLES)
def test_every_bundled_topology_routes_roles_and_mounts_marker_read_only(name):
    document = _compose(name)
    validate_scheduler_contract(document)
    services = document["services"]
    for service_name, role in COMPOSE_ROLES[name].items():
        service = services[service_name]
        assert service["command"][:2] == ["--role", role]
        assert any(
            str(volume).endswith(":/run/spaceworks-host:ro")
            for volume in service["volumes"]
        )


@pytest.mark.parametrize("name", COMPOSE_ROLES)
def test_candidate_backend_has_no_normal_migrate_dependency(name):
    candidate = _compose(name)["services"]["candidate-backend"]

    assert candidate["command"][:2] == ["--role", "backend"]
    assert "migrate" not in (candidate.get("depends_on") or {})


def test_external_scheduler_without_an_independent_gate_is_refused():
    topology = {
        "services": {"backend": {}},
        "x-spaceworks-host-orchestration": {"scheduler": {"mode": "external"}},
    }

    with pytest.raises(TopologyConfigurationError, match="neither"):
        validate_scheduler_contract(topology)

    with pytest.raises(TopologyConfigurationError, match="independent fence"):
        validate_scheduler_environment({"SPACEWORKS_SCHEDULER_MODE": "external"})


@pytest.mark.parametrize("field", ["host_gate_command", "control_plane_disablement"])
def test_external_scheduler_may_declare_either_independent_fence(field):
    topology = {
        "services": {"backend": {}},
        "x-spaceworks-host-orchestration": {
            "scheduler": {"mode": "external", field: "provider-control-plane fence"}
        },
    }

    assert validate_scheduler_contract(topology)[field]


def test_writer_rollout_must_equal_every_ordinary_image_writer():
    topology = _compose("docker-compose.prod.yml")
    topology["x-spaceworks-host-orchestration"]["writer_services"].remove("worker")

    with pytest.raises(TopologyConfigurationError, match="writer rollout"):
        from apps.backup.topology import validate_host_orchestration_contract

        validate_host_orchestration_contract(topology)


@pytest.mark.parametrize("name", COMPOSE_ROLES)
def test_renderable_compose_surface_contains_no_capability_record_facts(name):
    document = _compose(name)
    forbidden = {
        "RESTORE_ID", "SIBLING_DATABASE_NAME", "SIBLING_DATABASE_OID",
        "SERVER_IDENTITY", "OUTER_ARTIFACT_SHA256", "CAPTURE_ID",
        "CAPABILITY_NONCE", "CAPABILITY_ALLOWED_ROLE", "CAPABILITY_EXPIRY",
    }
    for service in document["services"].values():
        environment = service.get("environment") or {}
        keys = set(environment) if isinstance(environment, dict) else {
            str(item).split("=", 1)[0] for item in environment
        }
        assert keys.isdisjoint(forbidden)
        assert not any("/private" in str(volume) for volume in service.get("volumes", ()))
        command = str(service.get("command", ""))
        assert not any(name in command for name in forbidden)


@pytest.mark.parametrize("name", COMPOSE_ROLES)
def test_rendered_compose_config_contains_no_capability_record_facts(name):
    if shutil.which("docker") is None:
        pytest.skip("HOST-ONLY: Docker Compose CLI is unavailable")
    environment = {
        **os.environ,
        "POSTGRES_PASSWORD": "owner-password",
        "MINIO_ROOT_USER": "minio-user",
        "MINIO_ROOT_PASSWORD": "minio-password",
        "SECRET_KEY": "django-secret",
        "ALLOWED_HOSTS": "localhost",
        "DATABASE_URL": "postgres://app@candidate/candidate",
        "SPACEWORKS_DB_POINTER_GENERATION": "4",
        "SPACEWORKS_MAINTENANCE_DATABASE_URL": "postgres://owner@candidate/candidate",
        "API_CLIENT_ENC_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "AWS_ACCESS_KEY_ID": "access",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "AWS_S3_ENDPOINT_URL": "https://storage.internal",
        "AWS_S3_PUBLIC_ENDPOINT_URL": "https://storage.example",
        "PUBLIC_APP_BASE_URL": "https://app.example",
        "PUBLIC_IMAGE_BASE_URL": "https://storage.example/public",
        "DEFAULT_FROM_EMAIL": "noreply@example.test",
    }
    result = subprocess.run(
        ["docker", "compose", "-f", name, "config", "--format", "json"],
        cwd=ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )
    rendered = result.stdout
    for fact in (
        "RESTORE_ID", "SIBLING_DATABASE_NAME", "SIBLING_DATABASE_OID",
        "SERVER_IDENTITY", "OUTER_ARTIFACT_SHA256", "CAPTURE_ID",
        "CAPABILITY_NONCE", "CAPABILITY_ALLOWED_ROLE", "CAPABILITY_EXPIRY",
    ):
        assert fact not in rendered


@pytest.mark.parametrize("name", ["docker-compose.prod.yml", "docker-compose.cloud.yml"])
def test_production_containers_cannot_mount_private_ops_state(name):
    for service in _compose(name)["services"].values():
        destinations = set()
        for volume in service.get("volumes", ()):
            parts = str(volume).rsplit(":", 2)
            if len(parts) >= 2:
                destinations.add(
                    parts[-2] if parts[-1] in {"ro", "rw"} else parts[-1]
                )
        assert "/var/lib/spaceworks/ops" not in destinations


def test_every_marker_transition_invalidates_before_database_effects():
    source = (ROOT / "backend" / "scripts" / "transition_host_orchestration.py").read_text(
        encoding="utf-8"
    )

    assert source.index('invalidate_all("marker-transition")') < source.index(
        'with psycopg2.connect(os.environ["DATABASE_URL"])'
    )


def test_compose_wrapper_unsets_ambient_pointer_and_layers_pointer_last(tmp_path):
    static = tmp_path / "static.env"
    pointer = tmp_path / "ops" / "database-pointer.env"
    pointer.parent.mkdir()
    static.write_text(
        "SPACEWORKS_SCHEDULER_MODE=image\nSTATIC_ONLY=yes\n",
        encoding="utf-8",
    )
    pointer.write_text(
        "DATABASE_URL=postgres://pointer@db/candidate\n"
        "SPACEWORKS_DB_POINTER_GENERATION=9\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python3").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_bin / "docker").write_text(
        """#!/usr/bin/python3
import json, os, pathlib, sys
files = [sys.argv[index + 1] for index, value in enumerate(sys.argv) if value == '--env-file']
effective = {}
for name in files:
    for line in pathlib.Path(name).read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            if len(value) >= 2 and value[0] == value[-1] == "'":
                value = value[1:-1]
            effective[key] = value
pathlib.Path(os.environ['WRAPPER_OBSERVATION']).write_text(json.dumps({
    'ambient': os.environ.get('DATABASE_URL', '<unset>'),
    'generation': os.environ.get('SPACEWORKS_DB_POINTER_GENERATION', '<unset>'),
    'files': files,
    'effective_url': effective['DATABASE_URL'],
    'effective_generation': effective['SPACEWORKS_DB_POINTER_GENERATION'],
}))
""",
        encoding="utf-8",
    )
    (fake_bin / "python3").chmod(0o755)
    (fake_bin / "docker").chmod(0o755)
    observation = tmp_path / "observed.json"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DATABASE_URL": "postgres://ambient@wrong/wrong",
        "SPACEWORKS_DB_POINTER_GENERATION": "999",
        "SPACEWORKS_OPS_HOST_DIR": str(pointer.parent),
        "SPACEWORKS_STATIC_ENV_FILE": str(static),
        "WRAPPER_OBSERVATION": str(observation),
    }

    subprocess.run(
        [str(ROOT / "scripts" / "spaceworks-compose.sh"), "bundled", "config"],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    observed = json.loads(observation.read_text(encoding="utf-8"))
    assert observed["ambient"] == observed["generation"] == "<unset>"
    assert observed["files"] == [str(static), str(pointer)]
    assert observed["effective_url"] == "postgres://pointer@db/candidate"
    assert observed["effective_generation"] == "9"
