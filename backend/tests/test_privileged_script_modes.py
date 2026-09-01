"""The shipped scripts an operator or another script executes must be executable.

A script committed 0644 is invisible until the one moment it is executed, and then it
dies with "Permission denied". It has happened twice: `scripts/spaceworks-compose.sh`
took down the installer's first compose call from a fresh clone, and
`scripts/import-backup.sh` reached `exec "$ROOT/scripts/restore.sh"` only after it had
already recorded the restore intent and released its lock. Nothing chmods these at
install time - `install.sh` unpacks the release tarball, which carries whatever mode
git recorded - so the executable bit is part of the shipped contract, not a local
convenience.
"""

from pathlib import Path
import os
import re

import pytest

from apps.backup.producer_capability import PRIVILEGED_SCRIPT_NAMES


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)

# `exec "$ROOT/scripts/x.sh"` and friends: a direct execution, not `bash <script>`.
_DIRECT_EXECUTION = re.compile(
    r'exec\s+"\$(?:ROOT|INSTALL_DIR|SCRIPT_DIR)/(scripts/[A-Za-z0-9_-]+\.sh)"'
)


def _shipped_shell_scripts():
    return sorted(ROOT.glob("scripts/*.sh")) + [ROOT / "setup.sh", ROOT / "install.sh"]


@pytest.mark.parametrize(
    "name",
    ["install.sh"]
    + [f"scripts/{n}" for n in PRIVILEGED_SCRIPT_NAMES if n.endswith(".sh")],
)
def test_operator_entry_point_is_executable(name):
    """The curl entry point and every privileged shell script ship executable."""
    assert os.access(ROOT / name, os.X_OK), (
        f"{name} is shipped without its executable bit; an operator running it "
        "directly gets 'Permission denied'."
    )


def test_no_shipped_script_directly_executes_a_non_executable_sibling():
    """Whatever a script `exec`s must itself be executable in the release tarball."""
    checked = 0
    for script in _shipped_shell_scripts():
        if not script.exists():
            continue
        for target in _DIRECT_EXECUTION.findall(script.read_text(encoding="utf-8")):
            checked += 1
            assert os.access(ROOT / target, os.X_OK), (
                f"{script.name} directly executes {target}, which is not executable; "
                "that handoff dies with 'Permission denied'."
            )
    assert checked, "The direct-execution scan matched nothing; the pattern has rotted."
