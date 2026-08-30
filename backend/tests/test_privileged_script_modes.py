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
import re
import subprocess

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


# The executable bit must be read from GIT, not the working tree. This repository has
# `core.fileMode = false`, so `chmod +x` never reaches a commit and `os.access()` reports
# a local bit that no clone and no release tarball will ever see. That blind spot already
# cost a production fix: `scripts/restore.sh` was chmod'd 0755 and guarded here on
# 2026-08-25, the guard went green, and `git archive HEAD` still shipped it 0644 - so
# `import-backup.sh` still died at `exec .../restore.sh` with "Permission denied", after
# recording the restore intent and releasing its lock. `install.sh` unpacks the GitHub
# tarball with git's modes and chmods only itself and the compose wrapper, so for every
# other script git's mode IS the shipped mode. Set it with `git update-index --chmod=+x`.
def _git_file_mode(name):
    completed = subprocess.run(
        ["git", "ls-files", "-s", "--", name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip(), f"{name} is not tracked by git"
    return completed.stdout.split(None, 1)[0]


def _assert_ships_executable(name):
    mode = _git_file_mode(name)
    assert mode == "100755", (
        f"{name} is recorded in git as {mode}, so the release tarball ships it "
        "without its executable bit and running it gives 'Permission denied'. "
        f"Fix with: git update-index --chmod=+x {name}"
    )


@pytest.mark.parametrize(
    "name",
    ["install.sh"]
    + [f"scripts/{n}" for n in PRIVILEGED_SCRIPT_NAMES if n.endswith(".sh")],
)
def test_operator_entry_point_is_executable(name):
    """The curl entry point and every privileged shell script ship executable."""
    _assert_ships_executable(name)


def test_no_shipped_script_directly_executes_a_non_executable_sibling():
    """Whatever a script `exec`s must itself be executable in the release tarball."""
    checked = 0
    for script in _shipped_shell_scripts():
        if not script.exists():
            continue
        for target in _DIRECT_EXECUTION.findall(script.read_text(encoding="utf-8")):
            checked += 1
            mode = _git_file_mode(target)
            assert mode == "100755", (
                f"{script.name} directly executes {target}, which git records as "
                f"{mode}; that handoff dies with 'Permission denied' in the release "
                f"tarball. Fix with: git update-index --chmod=+x {target}"
            )
    assert checked, "The direct-execution scan matched nothing; the pattern has rotted."
