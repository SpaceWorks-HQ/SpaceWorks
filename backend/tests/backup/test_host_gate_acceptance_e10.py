"""Lane E section 11 host capability must be real, not a baseline placeholder."""

import pytest

from apps.backup import import_preflight


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: import preflight still reports the Lane E host restore gate as "
        "not configured"
    ),
)
def test_import_preflight_requires_an_installed_host_restore_gate():
    status = import_preflight.host_restore_gate_status()

    assert status != "not configured"
    assert status["protocol"] == "spaceworks-lane-e-b1-v1"
    assert status["privileged_script_sha256"]
    assert status["entrypoint_sha256"]
    assert status["signing_key_fingerprint"]
    assert status["migration_version"]
