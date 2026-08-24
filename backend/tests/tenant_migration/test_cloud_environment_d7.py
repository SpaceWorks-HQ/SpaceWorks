import pytest
import yaml

from apps.backup.cloud_environment import (
    CloudEnvironmentError,
    init_from_current_environment,
)
from apps.backup.host_pointer import read_pointer


def compose_file(tmp_path):
    path = tmp_path / "docker-compose.cloud.yml"
    document = {
        "services": {
            "backend": {
                "command": ["--role", "backend", "gunicorn"],
                "environment": {
                    "DATABASE_URL": "${DATABASE_URL:?required}",
                    "SPACEWORKS_DB_POINTER_GENERATION": (
                        "${SPACEWORKS_DB_POINTER_GENERATION:?required}"
                    ),
                    "SECRET_KEY": "${SECRET_KEY:?required}",
                    "OPTIONAL": "${OPTIONAL:-fallback}",
                },
            },
            "cron": {"command": ["--role", "cron", "cron"]},
        },
        "x-spaceworks-host-orchestration": {
            "scheduler": {"mode": "image", "services": ["cron"]},
            "pointer": {
                "mode": "atomic-file",
                "path": "/var/lib/spaceworks/ops/database-pointer.env",
                "static_environment": "/etc/spaceworks/cloud.env",
            },
            "database_identity": "endpoint-plus-queried-uuid",
            "sibling_lifecycle": "provider-isolated-database",
            "writer_services": ["backend", "cron"],
        },
    }
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_init_captures_invoking_environment_and_validates_host_rendering(tmp_path):
    compose = compose_file(tmp_path)
    static = tmp_path / "etc" / "cloud.env"
    pointer = tmp_path / "ops" / "database-pointer.env"
    topology = tmp_path / "ops" / "topology.json"
    observed = {}

    def compose_renderer(compose_path, static_env, pointer_path):
        observed.update(
            {
                "compose_path": compose_path,
                "static_env": static_env,
                "pointer_path": pointer_path,
            }
        )
        current = read_pointer(pointer, require_root_owned=False)
        services = {
            name: {"environment": {"DATABASE_URL": current.database_url}}
            for name in ("backend", "cron")
        }
        return yaml.safe_dump({"services": services})

    result = init_from_current_environment(
        compose_path=compose,
        static_env_path=static,
        pointer_path=pointer,
        topology_record_path=topology,
        environ={
            "DATABASE_URL": "postgres://runtime@db/active",
            "SECRET_KEY": "captured-once",
        },
        compose_renderer=compose_renderer,
        require_root_owned=False,
    )

    # _dotenv_line quotes only values outside [A-Za-z0-9_./:@,+-]; "captured-once" is safe, so it
    # is written unquoted. The OPTIONAL assertion below depends on that same rule.
    assert "SECRET_KEY=captured-once" in static.read_text(encoding="utf-8")
    assert "OPTIONAL=fallback" in static.read_text(encoding="utf-8")
    assert read_pointer(pointer, require_root_owned=False).generation == 1
    assert observed == {
        "compose_path": compose,
        "static_env": static,
        "pointer_path": pointer,
    }
    assert {item["name"] for item in result["variables"]} >= {
        "DATABASE_URL", "SECRET_KEY", "OPTIONAL"
    }
    assert all("value" not in item for item in result["variables"])


def test_init_refuses_a_missing_required_value_before_writing_files(tmp_path):
    compose = compose_file(tmp_path)
    static = tmp_path / "cloud.env"
    pointer = tmp_path / "pointer.env"

    with pytest.raises(CloudEnvironmentError, match="SECRET_KEY"):
        init_from_current_environment(
            compose_path=compose,
            static_env_path=static,
            pointer_path=pointer,
            topology_record_path=tmp_path / "topology.json",
            compose_renderer=lambda *_args: "",
            environ={"DATABASE_URL": "postgres://runtime@db/active"},
            require_root_owned=False,
        )

    assert not static.exists()
    assert not pointer.exists()
