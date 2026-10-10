"""GHCR listing and delete failures use bounded retries and never weaken graph safety."""

import pytest

from tests.test_ghcr_retention import ROOT, retention, protected

pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires repository scripts")


@pytest.mark.parametrize("outcome", ["offline", "bad-row", "1\t\tlatest", "\tsha256:root\tlatest"])
def test_failed_or_malformed_listing_vetoes_all_deletion(retention, protected, outcome):
    attempts, sleeps, deleted = [], [], []

    def runner(command):
        if "DELETE" in command:
            deleted.append(command)
        attempts.append(command)
        if outcome == "offline":
            raise retention.CommandError("provider unavailable")
        return outcome

    assert retention.clean_package("owner", "package", protected, runner=runner, sleeper=sleeps.append) is False
    assert deleted == []
    assert len(attempts) == (4 if outcome == "offline" else 1)
    assert sleeps == ([2, 4, 6] if outcome == "offline" else [])


def test_delete_failure_is_bounded_and_other_stale_versions_are_still_attempted(retention, protected, capsys):
    deleted, sleeps = [], []

    def runner(command):
        if "--paginate" in command:
            return "1\tsha256:old\told\n2\tsha256:older\tolder\n"
        if "DELETE" in command:
            deleted.append(command[-1])
            if command[-1].endswith("/1"):
                raise retention.CommandError("delete refused")
            return ""
        raise AssertionError(command)

    retention.clean_package("owner", "package", protected, runner=runner, sleeper=sleeps.append)
    assert len(deleted) == 5
    assert deleted[-1].endswith("/2")
    assert sleeps == [2, 4, 6]
    assert "Could not remove" in capsys.readouterr().out
