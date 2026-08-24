"""Lane E section 11 row 5: independent whole-source primitive coverage."""

import importlib
from pathlib import Path

import pytest


CASES = {
    "direct_raw_sql.py": "def write(cursor):\n    cursor.execute('DELETE FROM x')\n",
    "aliased_raw_sql.py": (
        "def write(cursor):\n    run = cursor.executemany\n"
        "    run('INSERT INTO x VALUES (%s)', [(1,)])\n"
    ),
    "object_client.py": "def write(s3):\n    s3.copy_object(Bucket='b', Key='k')\n",
    "settings_environment.py": (
        "import os\nfrom django.conf import settings as config\n"
        "VALUE = os.environ['SECRET_KEY']\nOTHER = config.AWS_STORAGE_BUCKET_NAME\n"
    ),
    "generated_path.py": (
        "def path(owner, token):\n    return f'evidence/{owner}/{token}.jpg'\n"
    ),
    "mixed_semantic.py": (
        "def write(row, payload):\n    row.meta = payload\n    row.save()\n"
    ),
    "direct_psql.sh": "psql \"$DATABASE_URL\" -c 'UPDATE x SET value=1'\n",
}


def _guard_module():
    try:
        return importlib.import_module("apps.backup.source_primitive_guard")
    except ModuleNotFoundError:
        pytest.fail(
            "SPEC GAP: apps.backup.source_primitive_guard does not exist; Lane E "
            "has no independent whole-source primitive inventory"
        )


@pytest.mark.xfail(
    strict=True,
    reason="SPEC GAP: the independent Lane E whole-source primitive guard is absent",
)
@pytest.mark.parametrize("relative", tuple(CASES))
def test_each_unregistered_whole_source_primitive_fails_independently(
    relative, tmp_path
):
    path = Path(tmp_path, relative)
    path.write_text(CASES[relative], encoding="utf-8")
    guard = _guard_module()

    with pytest.raises(guard.SourcePrimitiveCoverageError):
        guard.validate_whole_source_primitive_coverage(tmp_path, registry={})


@pytest.mark.xfail(
    strict=True,
    reason="SPEC GAP: reviewed-direct stable AST fingerprints are not implemented",
)
def test_moving_a_reviewed_direct_use_invalidates_its_fingerprint(tmp_path):
    path = tmp_path / "reviewed.py"
    path.write_text(CASES["direct_raw_sql.py"], encoding="utf-8")
    guard = _guard_module()
    discovered = guard.discover_whole_source_primitives(tmp_path)
    assert len(discovered) == 1
    reviewed = guard.reviewed_direct_entry(
        discovered[0],
        purpose="E10 reviewed test use",
        owner="main",
        disposition="registered raw mutation",
        reviewer="lane-e-e10",
    )

    path.write_text("\n" + CASES["direct_raw_sql.py"], encoding="utf-8")
    with pytest.raises(guard.SourcePrimitiveCoverageError, match="fingerprint"):
        guard.validate_whole_source_primitive_coverage(
            tmp_path, registry={reviewed.source_symbol: reviewed}
        )
