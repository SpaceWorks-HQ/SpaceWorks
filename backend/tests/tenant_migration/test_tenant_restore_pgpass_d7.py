from pathlib import Path
import stat
import subprocess

import pytest

from apps.tenant_migration.tenant_restore_database import PostgresSiblingLifecycle
from apps.tenant_migration.tenant_restore_pgpass import pg_restore_process_inputs
from apps.tenant_migration.tenant_restore_types import (
    ResourceIdentity,
    SiblingResource,
    TenantRestoreRefused,
)


def test_pg_restore_receives_no_database_secret_in_argv_or_inherited_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://admin:leak-me@db/active")
    monkeypatch.setenv("PGPASSWORD", "also-leak-me")
    observed = {}

    def run(argv, **kwargs):
        observed["argv"] = argv
        observed["environment"] = kwargs["env"]
        password_path = Path(kwargs["env"]["PGPASSFILE"])
        observed["password_path"] = password_path
        observed["password"] = password_path.read_text(encoding="utf-8")
        observed["mode"] = stat.S_IMODE(password_path.stat().st_mode)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(
        "apps.tenant_migration.tenant_restore_database.client_binary",
        lambda _tool, _major: "/usr/bin/pg_restore",
    )
    monkeypatch.setattr(
        "apps.tenant_migration.tenant_restore_database.subprocess.run", run
    )
    lifecycle = object.__new__(PostgresSiblingLifecycle)
    lifecycle.target_major = 16
    sibling = SiblingResource(
        ResourceIdentity("db:5432", "candidate", database_oid=42),
        "postgresql://runtime:p%40ssword@db:5432/candidate?sslmode=require",
        True,
        True,
        True,
    )

    lifecycle.restore(sibling, tmp_path / "database.dump")

    assert "p@ssword" not in " ".join(observed["argv"])
    assert "leak-me" not in repr(observed["environment"])
    assert "PGPASSWORD" not in observed["environment"]
    assert observed["environment"]["PGSSLMODE"] == "require"
    assert observed["password"] == "db:5432:candidate:runtime:p@ssword\n"
    assert observed["mode"] == 0o600
    assert not observed["password_path"].exists()


@pytest.mark.parametrize("port", [0, 65536])
def test_pg_restore_refuses_ports_outside_the_postgresql_range(port):
    with pytest.raises(TenantRestoreRefused, match="URL is (?:incomplete|invalid)"):
        with pg_restore_process_inputs(
            f"postgresql://runtime:secret@db:{port}/candidate"
        ):
            pass
