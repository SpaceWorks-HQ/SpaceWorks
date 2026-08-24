from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
INVARIANTS_PATH = REPO_ROOT / "docs" / "INVARIANTS.md"
pytestmark = pytest.mark.skipif(
    not INVARIANTS_PATH.exists(),
    reason="host-only: repo root is not in the test image",
)


def test_core_dumps_process_dumps_and_swap_are_explicitly_outside_the_dek_guarantee():
    operator_documentation = INVARIANTS_PATH.read_text(encoding="utf-8").lower()

    assert "core dumps" in operator_documentation
    assert "process dumps" in operator_documentation
    assert "swap" in operator_documentation
    assert "outside" in operator_documentation


def test_cache_clearing_is_documented_as_best_effort_not_secure_zeroization():
    operator_documentation = INVARIANTS_PATH.read_text(encoding="utf-8").lower()

    assert "cache clearing is best effort" in operator_documentation
    assert "not secure zeroization" in operator_documentation
