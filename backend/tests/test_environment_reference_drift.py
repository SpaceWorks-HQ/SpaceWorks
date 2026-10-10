"""Every environment variable the backend reads is documented (cloud lane).

`settings_policy.ENV_SURFACE` is already pinned to exactly what the code reads
(`test_env_surface_drift.py`). At `b7c2ee93` 167 of its 247 names appeared in no doc at all,
so an operator had nowhere to look up `SECURE_SSL_REDIRECT`, `INFRA_HOSTS` or any rate
limit. `docs/environment-reference.md` is the complete list, and this keeps it complete in
both directions.
"""

import re
from pathlib import Path

from apps.backup.settings_policy import ENV_SURFACE

DOC = Path(__file__).resolve().parents[2] / "docs" / "environment-reference.md"
REFERENCE_DOCS = (DOC, DOC.with_name("environment-reference-delivery.md"))


def _documented():
    return set().union(*(
        set(re.findall(r"^\| `([A-Z0-9_]+)` \|", path.read_text(encoding="utf-8"), re.M))
        for path in REFERENCE_DOCS
    ))


def test_every_environment_variable_is_in_the_reference():
    missing = sorted(set(ENV_SURFACE) - _documented())
    assert not missing, (
        f"docs/environment-reference.md does not document {missing}. Add a row in the "
        f"right section with its default and what it is for."
    )


def test_the_reference_lists_nothing_the_backend_does_not_read():
    stale = sorted(_documented() - set(ENV_SURFACE))
    assert not stale, f"docs/environment-reference.md documents {stale}, which nothing reads"


def test_the_production_compose_file_passes_the_observability_opt_ins():
    """Documented but inert: no compose service uses env_file, so a value in `.env`
    only reaches Django through an explicit `environment:` entry."""
    import yaml

    root = DOC.parents[1]
    for name in ("docker-compose.prod.yml", "docker-compose.cloud.yml"):
        document = yaml.safe_load((root / name).read_text(encoding="utf-8"))
        backend = document["services"]["backend"]["environment"]
        for key in ("METRICS_TOKEN", "SENTRY_DSN", "SENTRY_TRACES_SAMPLE_RATE", "SENTRY_ENVIRONMENT"):
            assert key in backend, f"{name} does not pass {key} to the backend"
