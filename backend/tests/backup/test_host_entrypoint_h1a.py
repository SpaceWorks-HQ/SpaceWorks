import json
from pathlib import Path

import pytest

from apps.backup.host_marker import DatabaseIdentity, MarkerError, MarkerState, marker_payload, read_marker
from apps.backup.process_roles import ProcessRole, admission_for
from scripts import spaceworks_entrypoint as entrypoint


EXPECTED = {
    MarkerState.NORMAL: set(ProcessRole),
    MarkerState.CANDIDATE_PREPARATION: {ProcessRole.MIGRATE},
    MarkerState.CANDIDATE_HEALTH: {ProcessRole.BACKEND},
    MarkerState.QUARANTINED_AFTER_CUTOVER: {ProcessRole.BACKEND},
    MarkerState.ACKNOWLEDGED_NORMAL: set(ProcessRole),
}


@pytest.fixture(autouse=True)
def _allow_unprivileged_temp_markers(monkeypatch):
    monkeypatch.setattr(
        entrypoint,
        "read_marker",
        lambda path: read_marker(path, require_root_owned=False),
    )


@pytest.mark.parametrize("state", MarkerState)
@pytest.mark.parametrize("role", ProcessRole)
def test_every_marker_state_has_an_exact_role_matrix(state, role):
    decision = admission_for(state, role)

    assert decision.admitted is (role in EXPECTED[state])
    assert decision.requires_capability is (
        state == MarkerState.CANDIDATE_HEALTH and role == ProcessRole.BACKEND
    )


def _write(path, state=MarkerState.NORMAL):
    path.write_text(
        json.dumps(marker_payload(state, DatabaseIdentity("spaceworks", 42))),
        encoding="utf-8",
    )


@pytest.mark.parametrize("role", [ProcessRole.WORKER, ProcessRole.BEAT, ProcessRole.CRON,
                                  ProcessRole.MIGRATE, ProcessRole.MANAGEMENT])
def test_candidate_health_refuses_non_backend_before_capability_parsing(
    tmp_path, monkeypatch, role
):
    marker = tmp_path / "marker.json"
    _write(marker, MarkerState.CANDIDATE_HEALTH)
    monkeypatch.setenv("SPACEWORKS_HOST_MARKER_PATH", str(marker))
    called = False

    def capability(*_args):
        nonlocal called
        called = True

    result = entrypoint.main(
        ["entrypoint", "--role", role.value, "true"],
        capability_request=capability,
    )

    assert result == 78
    assert called is False


def test_candidate_backend_passes_live_identity_to_capability_before_exec(tmp_path, monkeypatch):
    marker = tmp_path / "marker.json"
    _write(marker, MarkerState.CANDIDATE_HEALTH)
    monkeypatch.setenv("SPACEWORKS_HOST_MARKER_PATH", str(marker))
    monkeypatch.setenv("DATABASE_URL", "postgres://runtime@example/spaceworks")
    monkeypatch.setattr(entrypoint, "live_database_identity", lambda _url: ("spaceworks", 42))
    observed = []
    monkeypatch.setattr(entrypoint.os, "execvp", lambda *args: observed.append(args))

    result = entrypoint.main(
        ["entrypoint", "--role", "backend", "gunicorn"],
        capability_request=lambda marker, identity: observed.append((marker.state, identity)),
    )

    assert result is None
    assert observed == [
        (MarkerState.CANDIDATE_HEALTH, ("spaceworks", 42)),
        ("gunicorn", ["gunicorn"]),
    ]


@pytest.mark.parametrize("kind", ["missing", "malformed", "unknown", "unreadable"])
@pytest.mark.parametrize("role", ProcessRole)
def test_bad_marker_fails_closed_for_every_role(tmp_path, monkeypatch, kind, role):
    marker = tmp_path / "marker.json"
    if kind == "malformed":
        marker.write_text("{", encoding="utf-8")
    elif kind == "unknown":
        payload = marker_payload(MarkerState.NORMAL, DatabaseIdentity("spaceworks", 42))
        payload["state"] = "surprise"
        marker.write_text(json.dumps(payload), encoding="utf-8")
    elif kind == "unreadable":
        marker.write_text("{}", encoding="utf-8")
        original = Path.read_text

        def refused_read(path, *args, **kwargs):
            if path == marker:
                raise PermissionError("refused")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", refused_read)
    monkeypatch.setenv("SPACEWORKS_HOST_MARKER_PATH", str(marker))

    assert entrypoint.main(["entrypoint", "--role", role.value, "true"]) == 78


def test_marker_parser_rejects_unknown_fields(tmp_path):
    marker = tmp_path / "marker.json"
    payload = marker_payload(MarkerState.NORMAL, DatabaseIdentity("spaceworks", 42))
    payload["capability"] = "file-based-fallback"
    marker.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MarkerError, match="top-level"):
        read_marker(marker, require_root_owned=False)


def test_candidate_preparation_marker_must_name_a_non_routable_sibling(tmp_path):
    marker = tmp_path / "marker.json"
    payload = marker_payload(
        MarkerState.CANDIDATE_PREPARATION,
        DatabaseIdentity("spaceworks_candidate", 84),
    )
    payload["database"]["routing"] = "active"
    marker.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MarkerError, match="routing"):
        read_marker(marker, require_root_owned=False)
