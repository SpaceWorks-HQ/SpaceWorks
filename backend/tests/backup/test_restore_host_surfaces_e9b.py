"""HOST-ONLY: repository scripts/ and Compose files are absent from backend images."""

from pathlib import Path
import re

import pytest

from apps.backup.route_policy import route_allowed


ROOT = Path(__file__).resolve().parents[3]
RESTORE = ROOT / "scripts" / "restore.sh"
PRODUCTION_COMPOSE = ROOT / "docker-compose.prod.yml"
pytestmark = pytest.mark.skipif(
    not RESTORE.exists() or not PRODUCTION_COMPOSE.exists(),
    reason="HOST-ONLY: scripts and Compose files are outside the backend test image",
)


def test_every_legacy_pg_restore_reprovisions_before_later_django_commands():
    script = RESTORE.read_text(encoding="utf-8")
    restores = [match.start() for match in re.finditer(r"\bpg_restore --", script)]
    reprovisions = [
        match.start() for match in re.finditer(
            r"\breprovision_grants(?=[\s;])", script
        )
    ]
    # The four calls pair exactly with cleanup rollback, crash rollback, the
    # temporary diff sibling, and final replacement. The function declaration
    # has a following "(" and is deliberately not matched.
    assert len(restores) == len(reprovisions) == 4
    assert all(restore < grant for restore, grant in zip(restores, reprovisions, strict=True))
    assert all(
        grant < next_restore
        for grant, next_restore in zip(reprovisions, restores[1:], strict=False)
    )
    main_restore = script.index("say \"Replacing the database.\"")
    first_django_after_main = script.index("control rehydrate", main_restore)
    main_grants = script.index("reprovision_grants", main_restore)
    assert main_restore < main_grants < first_django_after_main


def test_quarantined_candidate_is_probeable_without_a_migrate_dependency():
    compose = PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    candidate = compose.split("  candidate-backend:", 1)[1].split("\n  frontend:", 1)[0]
    assert "/api/v1/health/readiness/" in candidate
    assert "      migrate:" not in candidate
    assert route_allowed("quarantined", "readiness", "GET")
    assert route_allowed("target_import", "readiness", "GET")


def test_legacy_wrapper_validates_before_claiming_or_pausing():
    script = RESTORE.read_text(encoding="utf-8")
    admission = script.index('preflight_result="$(restore_preflight')
    claim = script.index('claim_result="$(control claim')
    assert admission < claim
    cleanup = script.split("cleanup() {", 1)[1].split("trap cleanup EXIT", 1)[0]
    assert 'elif [[ "$claimed" == 1 ]]' in cleanup
