"""HOST-ONLY: Lane E role/grant recreation must precede Django startup."""

from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESTORE_SCRIPT = REPOSITORY_ROOT / "scripts" / "restore.sh"
pytestmark = pytest.mark.skipif(
    not RESTORE_SCRIPT.exists(),
    reason="HOST-ONLY: scripts/restore.sh is outside the backend test image",
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: scripts/restore.sh starts Django without first recreating the "
        "candidate runtime roles and grants"
    ),
)
def test_candidate_roles_and_grants_are_recreated_before_any_django_setup():
    source = RESTORE_SCRIPT.read_text(encoding="utf-8")
    django_start = source.index("django.setup()")
    grant_markers = (
        "provision-runtime-role",
        "recreate-runtime-roles",
        "apply-candidate-database-grants",
    )
    grant_positions = [
        source.index(marker) for marker in grant_markers if marker in source
    ]

    assert grant_positions, "restore supervisor has no role/grant recreation step"
    assert max(grant_positions) < django_start
