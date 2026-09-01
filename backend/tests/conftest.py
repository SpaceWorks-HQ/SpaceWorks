import os

import pytest
from cryptography.fernet import Fernet
from apps.ed25519 import encode_key, generate_keypair
from django.core.cache import cache
from django.db import connection
from django.db.backends.base.base import BaseDatabaseWrapper
from django.test import SimpleTestCase


# Reuse the deployment key when the environment supplies one: migration 0004
# provisions the global scope key WRAPPED WITH IT, so generating a different key here
# would make that row un-unwrappable and every audit row silently unattested.
_TEST_AUDIT_MAC_MASTER_KEY = (
    os.environ.get("AUDIT_MAC_MASTER_KEY")
    or Fernet.generate_key().decode("ascii")
)
_TEST_BACKUP_PRIVATE_RAW, _TEST_BACKUP_PUBLIC_RAW = generate_keypair()
_TEST_BACKUP_PRIVATE_KEY = encode_key(_TEST_BACKUP_PRIVATE_RAW)
_TEST_BACKUP_PUBLIC_KEY = encode_key(_TEST_BACKUP_PUBLIC_RAW)


@pytest.fixture(autouse=True)
def disable_axes_by_default(settings, request):
    settings.AXES_ENABLED = False
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.AUDIT_MAC_MASTER_KEY = _TEST_AUDIT_MAC_MASTER_KEY
    settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY = _TEST_BACKUP_PRIVATE_KEY
    settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY = _TEST_BACKUP_PUBLIC_KEY
    _reset_axes_state(request)
    yield
    settings.AXES_ENABLED = False
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.AUDIT_MAC_MASTER_KEY = _TEST_AUDIT_MAC_MASTER_KEY
    settings.BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY = _TEST_BACKUP_PRIVATE_KEY
    settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY = _TEST_BACKUP_PUBLIC_KEY
    _reset_axes_state(request)


def _reset_axes_state(request):
    cache.clear()

    try:
        from axes.handlers.proxy import AxesProxyHandler
        from axes.utils import reset
    except Exception:
        return

    AxesProxyHandler.implementation = None

    if not request.node.get_closest_marker("django_db"):
        return
    if connection.needs_rollback:
        return

    request.getfixturevalue("db")
    try:
        reset()
    except NotImplementedError:
        pass

@pytest.fixture(autouse=True)
def ensure_global_pii_write_fence(request):
    """Keep the singleton global PII write-fence present for DB tests.

    The H4 migration seeds ``PiiGlobalWriteFence`` (pk=1), but a transactional
    test's flush truncates it, which would make later transactional mapped
    writes and fence tests fail closed on a spuriously missing global fence.
    Re-seed it (open) before each DB test to preserve the production invariant.
    """
    if not request.node.get_closest_marker("django_db"):
        return
    if connection.needs_rollback:
        return
    request.getfixturevalue("db")
    from apps.encryption.models import PiiGlobalWriteFence

    PiiGlobalWriteFence.objects.get_or_create(pk=1)


@pytest.fixture(autouse=True)
def ensure_deployment_recovery_state(request):
    """Mirror the migration-seeded routing singleton after transactional flushes."""
    if not request.node.get_closest_marker("django_db") or connection.needs_rollback:
        return
    request.getfixturevalue("db")
    from apps.backup.models import DeploymentRecoveryState

    DeploymentRecoveryState.objects.get_or_create(pk=1)


@pytest.fixture(autouse=True)
def ensure_global_audit_mac_key(request, settings):
    """Mirror the deploy-time global-key provisioning invariant in DB tests."""
    settings.AUDIT_MAC_MASTER_KEY = _TEST_AUDIT_MAC_MASTER_KEY
    # This is a GENERATOR fixture, so every path must yield exactly once. A bare return
    # here raises "did not yield a value" and errors the test at setup -- which hits every
    # test that is not marked django_db, i.e. most of the suite.
    if (
        not request.node.get_closest_marker("django_db")
        or connection.needs_rollback
    ):
        yield
        return
    request.getfixturevalue("db")
    from apps.audit.keys import audit_mac_key_cache, provision_audit_mac_key

    audit_mac_key_cache.clear()
    provision_audit_mac_key()
    yield
    audit_mac_key_cache.clear()


@pytest.fixture(autouse=True)
def evidence_objects_exist_by_default(monkeypatch):
    from apps.evidence import storage

    monkeypatch.setattr("apps.evidence.storage.object_exists", lambda key: True)

    def validate(object_key):
        if not storage.object_exists(object_key):
            raise storage.EvidenceObjectValidationError(
                "missing", "Evidence object was not found."
            )
        return storage.EvidenceValidationResult(size=123, content_type="image/jpeg")

    monkeypatch.setattr("apps.evidence.storage.validate_evidence_object", validate)



@pytest.fixture(autouse=True)
def all_modules_enabled_for_test_makerspaces(monkeypatch):
    """Give makerspaces created in tests every module.

    Modules are opt-in in production: a new makerspace gets core plus whatever
    install profile the operator chose. Almost every test here exercises a specific
    module's behaviour rather than the install default, so without this they would
    each have to enable the module under test -- noise that says nothing about the
    thing being tested.

    Only the *field* default is patched. Anything that reads
    `default_enabled_module_keys()` / `DEFAULT_ENABLED_MODULES` directly still sees
    the real opt-in value, which is how tests/makerspaces/test_module_registry.py and
    test_module_install.py keep asserting the production default.
    """
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.module_profiles import EVERYTHING, profile_modules

    field = Makerspace._meta.get_field("enabled_modules")
    monkeypatch.setattr(field, "default", lambda: profile_modules(EVERYTHING))


class _EveryDatabase(frozenset):
    """A `databases` allow-set that also admits aliases created after setup.

    Iteration still yields only the real aliases, so Django's teardown flushes
    exactly the databases it created.
    """

    def __contains__(self, alias):
        return True


def _guarded_test_case():
    """The TestCase whose undeclared-database guard is currently installed.

    Django closes over the test class when it patches `ensure_connection`, and
    that class attribute is the only place the allow-set can be widened.
    """
    patched = BaseDatabaseWrapper.ensure_connection
    for cell in patched.__closure__ or ():
        value = cell.cell_contents
        if isinstance(value, type) and issubclass(value, SimpleTestCase):
            return value
    return None


@pytest.fixture
def allow_projection_databases():
    """Let a test open the short-lived databases it creates mid-test.

    Django rejects connections to aliases that did not exist when the test class
    was set up, which is the right default. The readable-main projection, the E7
    reconstruction verifier and the Lane D scratch projection each create,
    register and drop a real database mid-test, and `databases="__all__"` cannot
    express that because it is snapshotted at setup. The allow-set is widened for
    the duration and restored before class teardown unwraps the guard.

    Lives here rather than in one test module because three separate test
    packages need it.
    """
    case = _guarded_test_case()
    if case is None:
        yield
        return
    original = case.databases
    case.databases = _EveryDatabase(original)
    try:
        yield
    finally:
        case.databases = original
