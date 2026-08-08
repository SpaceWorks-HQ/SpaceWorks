"""Deploy-manifest drift guard (plan Track D, phase 15).

`a9cd82c` fixed one instance of a class of bug: a setting the code reads that no deploy
manifest passes. `PUBLIC_APP_BASE_URL` defaulted to a localhost URL, so password-reset
links worked when you tested from the server console and were unclickable for every real
user. Nothing failed, nothing logged. This file is the test that would have caught it.

The naive contract -- "every env var the code reads appears in every manifest" -- is the
wrong one, and worth saying why so it does not get re-litigated. The backend reads ~134
variables and all but two have defaults; most are tuning knobs (`THROTTLE_*`, TTLs, size
caps) whose defaults are correct in production and which would be noise in a manifest.
Requiring them all would make `.env.example` an unreadable reference and train everyone
to add exemptions.

The discriminator is not "does it have a default" but **"does its default work off-box"**.
A default of 300 seconds is right everywhere. A default of `http://localhost:9000` is
right only where the browser and the server are the same machine, which is exactly the
deployment nobody actually runs and exactly the one a developer tests from. So:

* on-box defaults in `settings.py` must be overridden by the production manifests;
* the same for on-box fallbacks written at the **consumer**, which is where
  `PUBLIC_APP_BASE_URL` hid -- its `settings.py` default is a harmless `""` and the
  localhost string lives in `platform.py`, so a settings-only scan misses it entirely;
* no manifest may set a variable the backend never reads, which is how a rename leaves a
  manifest quietly passing a dead name;
* and the proxy/TLS posture must be explicit rather than defaulted, because both of its
  wrong answers are silent.
"""

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO_ROOT / "backend"
SETTINGS = BACKEND / "config" / "settings.py"

# Manifests that describe a real, off-box production deployment. The dev compose file and
# the machine-specific override are deliberately absent: their whole job is to point the
# stack at localhost.
#
# `deploy/render.managed.yaml` is here because a second blueprint is exactly the kind of
# file that rots -- it is not what Render picks up by default, so nobody deploys it by
# accident and notices. It shares most of its surface with the root blueprint, and the
# guard is what keeps the two in step.
PRODUCTION_MANIFESTS = (
    "render.yaml",
    "docker-compose.prod.yml",
    "deploy/render.managed.yaml",
)

# The services that run backend Python. docker-compose hands them one environment block
# through a YAML anchor, so a variable added to `backend` alone does not reach the others
# -- which is why the keys are collected per service and intersected, not unioned.
BACKEND_SERVICES = ("backend", "migrate", "worker", "beat")

# A default is "on-box" when it names this machine or a compose service hostname: correct
# only where the browser, the backend and the storage are all the same host.
ON_BOX = re.compile(
    r"localhost|127\.0\.0\.1|0\.0\.0\.0|://minio|://backend|://redis|://db\b|:8000|:5000|:9000",
    re.IGNORECASE,
)

# Read implicitly by `env.db()` rather than by name, so no scan can see it.
IMPLICIT_READS = frozenset({"DATABASE_URL", "DEBUG"})

# Set for the *frontend* container's runtime config, not for backend Python. Not orphans.
FRONTEND_KEYS = frozenset({"TENANT_API_URL", "TENANT_TOKEN"})

# Consumed by the images, the compose file itself or an infrastructure container rather
# than by Django. Each is legitimately absent from the Python side.
INFRASTRUCTURE_KEYS = frozenset({
    "POSTGRES_PASSWORD", "POSTGRES_USER", "POSTGRES_DB",
    "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD",
    "MINIO_API_CORS_ALLOW_ORIGIN", "MINIO_CORS_ALLOWED_ORIGINS",
    "MINIO_BROWSER_REDIRECT_URL", "MC_HOST_local",
    "COMPOSE_PROJECT_NAME", "HTTP_PORT", "PORT", "WEB_CONCURRENCY",
    "MAKERSPACE_BACKEND_IMAGE", "MAKERSPACE_FRONTEND_IMAGE", "MAKERSPACE_IMAGE_TAG",
    "DEV_UID", "DEV_GID",
})

# On-box defaults a production manifest need not override, with the reason. Keep this
# short: every entry is a place the guard has been told to look away.
ON_BOX_EXEMPT = {
    # An allowlist of *internal* hostnames used to recognise infrastructure callers.
    # Its default names container hostnames on purpose and is not browser-facing.
    "INFRA_HOSTS": "internal caller allowlist; container hostnames are the point",
}


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

def _env_calls():
    """Every `env(...)`/`env.list(...)`/... call in settings.py, as (name, default_src)."""
    tree = ast.parse(SETTINGS.read_text(encoding="utf-8-sig"))
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_env = (isinstance(func, ast.Name) and func.id == "env") or (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "env"
        )
        if not is_env or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        default = next(
            (kw.value for kw in node.keywords if kw.arg == "default"),
            node.args[1] if len(node.args) > 1 else None,
        )
        calls.append((first.value, None if default is None else ast.unparse(default)))
    return calls


def _python_files():
    for path in BACKEND.rglob("*.py"):
        parts = path.parts
        if any(p in {"__pycache__", "migrations", ".venv", "tests"} for p in parts):
            continue
        yield path


def _direct_env_reads():
    names = set()
    for path in _python_files():
        source = path.read_text(encoding="utf-8-sig")
        names.update(re.findall(r'os\.(?:environ\.get|getenv)\(\s*["\']([A-Z0-9_]+)["\']', source))
    names.discard("DJANGO_SETTINGS_MODULE")
    return names


def _names_the_backend_reads():
    return {name for name, _ in _env_calls()} | _direct_env_reads() | set(IMPLICIT_READS)


def _consumer_on_box_fallbacks():
    """Settings whose on-box literal lives at the use site, not in settings.py.

    Matches `settings.X or "<on-box literal>"` -- the shape that hid
    `PUBLIC_APP_BASE_URL`, whose settings default is a blameless empty string.
    """
    found = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
                continue
            setting = next(
                (
                    v.attr
                    for v in node.values
                    if isinstance(v, ast.Attribute)
                    and isinstance(v.value, ast.Name)
                    and v.value.id == "settings"
                ),
                None,
            )
            if setting is None:
                continue
            for value in node.values:
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and ON_BOX.search(value.value)
                ):
                    found.setdefault(setting, str(path.relative_to(REPO_ROOT)))
    return found


def _manifest_backend_keys(name):
    """Keys a manifest sets for every backend-running service.

    Render keeps one `envVarGroup` shared by web/worker/beat, so its keys apply to all
    three. Compose defines them per service, and the anchor makes it easy to add a key to
    one service and believe it reached the rest -- so the intersection is what counts.
    """
    document = yaml.safe_load((REPO_ROOT / name).read_text(encoding="utf-8-sig"))
    if "render" in Path(name).name:
        keys = set()
        for group in document.get("envVarGroups") or ():
            keys.update(var["key"] for var in group.get("envVars") or ())
        for service in document.get("services") or ():
            keys.update(
                var["key"] for var in service.get("envVars") or () if "key" in var
            )
        return keys

    services = document.get("services") or {}
    per_service = [
        set((services[svc].get("environment") or {}).keys())
        for svc in BACKEND_SERVICES
        if svc in services
    ]
    assert per_service, f"{name} defines none of {BACKEND_SERVICES}"
    return set.intersection(*per_service)


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("manifest", PRODUCTION_MANIFESTS)
def test_on_box_defaults_are_overridden_by_production_manifests(manifest):
    """A localhost default is right on the server console and wrong for every real user."""
    on_box = {
        name
        for name, default in _env_calls()
        if default and ON_BOX.search(default) and name not in ON_BOX_EXEMPT
    }
    assert on_box, "the scan found no on-box defaults at all -- it has stopped working"

    missing = sorted(on_box - _manifest_backend_keys(manifest))

    assert not missing, (
        f"{manifest} does not set {missing}, whose settings.py defaults name this "
        f"machine. Set them in the manifest, or add an entry to ON_BOX_EXEMPT saying "
        f"why the on-box default is correct off-box."
    )


@pytest.mark.parametrize("manifest", PRODUCTION_MANIFESTS)
def test_consumer_side_on_box_fallbacks_are_overridden_by_production_manifests(manifest):
    """The PUBLIC_APP_BASE_URL shape: blank default in settings, localhost at the use site."""
    fallbacks = _consumer_on_box_fallbacks()
    assert "PUBLIC_APP_BASE_URL" in fallbacks, (
        "PUBLIC_APP_BASE_URL's consumer fallback is the case this scan exists for; "
        "if it moved, point the scan at wherever it went rather than deleting this"
    )

    keys = _manifest_backend_keys(manifest)
    missing = sorted(name for name in fallbacks if name not in keys)

    assert not missing, (
        f"{manifest} does not set {missing}. Their settings.py defaults look harmless "
        f"(usually \"\"), but the consumer substitutes a localhost URL when they are "
        f"blank: " + ", ".join(f"{n} in {p}" for n, p in sorted(fallbacks.items()))
    )


@pytest.mark.parametrize(
    "manifest", (*PRODUCTION_MANIFESTS, "docker-compose.yml"),
)
def test_manifests_do_not_set_variables_the_backend_never_reads(manifest):
    """Reverse drift: a rename leaves the manifest passing a name nothing reads."""
    known = _names_the_backend_reads() | FRONTEND_KEYS | INFRASTRUCTURE_KEYS
    orphans = sorted(
        key
        for key in _manifest_backend_keys(manifest)
        if key not in known and not key.startswith("VITE_")
    )

    assert not orphans, (
        f"{manifest} sets {orphans}, which no backend code reads. Either the code that "
        f"read them was renamed and the manifest was not, or they belong in "
        f"INFRASTRUCTURE_KEYS with a note about what consumes them."
    )


@pytest.mark.parametrize("manifest", PRODUCTION_MANIFESTS)
def test_the_proxy_posture_is_explicit_in_every_production_manifest(manifest):
    """Both wrong answers about proxies are silent, so neither may be reached by default.

    `TRUSTED_PROXY_COUNT` unset leaves DRF's legacy client-IP behaviour: behind a proxy
    that collapses traffic to one source address, every user shares a throttle bucket, and
    where the raw forwarded header is used instead a client can spoof its way out of one.
    A deployment that terminates TLS at a proxy has to state how many proxies it trusts,
    and `TRUST_X_FORWARDED_PROTO` has to be a decision rather than a default.
    """
    keys = _manifest_backend_keys(manifest)
    missing = sorted({"TRUSTED_PROXY_COUNT", "TRUST_X_FORWARDED_PROTO"} - keys)

    assert not missing, (
        f"{manifest} leaves {missing} at their defaults. Set the proxy count to the "
        f"number of proxies actually in front of the backend (0 disables forwarded-header "
        f"trust) so throttling keys on the real client IP."
    )
