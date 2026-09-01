"""The root `VERSION` file and the OpenAPI document version must not drift.

`VERSION` is the release series the GitHub Actions workflow reads to build the tag and the
release title; `SPECTACULAR_SETTINGS["VERSION"]` is what the published API document and the
generated client advertise. They were decoupled for a long time (`0.1.0` against a `VERSION`
that had climbed to `0.5.1`), which meant every schema consumer was told a version that had
never been true of anything.

Why a drift guard rather than reading the file at import time: the backend image is built
with `context: ./backend`, so the repo root is outside the build context and `VERSION` simply
does not exist inside the container. Settings that read it would crash at boot. This mirrors
the `features.ts` mirror guard -- hand-kept in two places, with a test that fails when they
disagree.
"""

from pathlib import Path

import pytest
from django.conf import settings


VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def test_the_openapi_version_matches_the_release_series():
    if not VERSION_FILE.exists():
        # The container case described in the module docstring: `./backend` is mounted at
        # /app and the repo root is not. Skipping keeps `exec backend pytest` honest
        # instead of reporting a phantom failure; the guard still runs on the host and CI.
        pytest.skip("VERSION is outside the backend build context")

    declared = VERSION_FILE.read_text().strip()

    assert declared == settings.SPECTACULAR_SETTINGS["VERSION"], (
        f"VERSION says {declared!r} but SPECTACULAR_SETTINGS says "
        f"{settings.SPECTACULAR_SETTINGS['VERSION']!r} -- bump both, then regenerate "
        f"frontend/openapi-schema.json and frontend/src/generated/api.ts."
    )


def test_the_release_series_is_a_semantic_version():
    """The release workflow hard-fails on a malformed VERSION; catch it before CI does."""
    import re

    if not VERSION_FILE.exists():
        pytest.skip("VERSION is outside the backend build context")

    declared = VERSION_FILE.read_text().strip()

    assert re.fullmatch(r"\d+\.\d+\.\d+", declared), (
        f"VERSION must be a semantic version like 1.0.0 (got {declared!r})"
    )
