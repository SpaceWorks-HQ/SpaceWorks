"""Plan B4 — the separability registries and their fail-closed system checks.

The behaviour under test is the *refusal*, not the happy path. Both gaps guarded
here fail OPEN if unguarded: a missing PII registration stores plaintext with
nothing raised, and a missing purge plan leaks private S3 objects forever. So every
test asserts that the system stops, and one asserts it stops *before* any write.
"""

import pytest
from django.apps import apps as django_apps

from apps.encryption.crypto import UnmappedPiiModel
from apps.encryption.mappers import ScopedPiiModelMixin
from apps.separability import checks
from apps.separability.registry import (
    RegistryError,
    is_finalized,
    pii_fields_for,
    register_pii_fields,
    register_purge_plan,
    registered_pii_models,
    registered_purge_modules,
    runtime_active,
)


def _ids(errors):
    return sorted(error.id for error in errors)


def _pii_models():
    return [
        model
        for model in django_apps.get_models()
        if issubclass(model, ScopedPiiModelMixin) and not model._meta.abstract
    ]


# --------------------------------------------------------------------------
# The live assertion: production configuration is complete.
# --------------------------------------------------------------------------

def test_every_mapped_model_has_a_pii_registration():
    """The check that would have caught an unregistered mapped model."""
    unregistered = [m._meta.label for m in _pii_models() if not pii_fields_for(m._meta.label)]
    assert unregistered == []


def test_production_registries_pass_every_check():
    assert checks.check_pii_registry_is_complete(None) == []
    assert checks.check_purge_registry_is_complete(None) == []
    assert checks.check_registries_are_frozen(None) == []


def test_registries_are_frozen_after_startup():
    assert is_finalized()


# --------------------------------------------------------------------------
# The refusals.
# --------------------------------------------------------------------------

def test_missing_pii_registration_is_a_startup_error(monkeypatch):
    """Drop one model's registration; the check must refuse to start."""
    victim = _pii_models()[0]._meta.label
    surviving = {
        label: pii_fields_for(label) for label in registered_pii_models() if label != victim
    }
    monkeypatch.setattr(
        "apps.separability.registry.pii_fields_for",
        lambda label: surviving.get(label, ()),
    )
    monkeypatch.setattr(
        "apps.separability.registry.registered_pii_models",
        lambda: frozenset(surviving),
    )

    errors = checks.check_pii_registry_is_complete(None)

    assert "separability.E001" in _ids(errors)
    assert victim in errors[0].msg


def test_pii_registration_for_a_nonexistent_model_is_an_error(monkeypatch):
    monkeypatch.setattr(
        "apps.separability.registry.registered_pii_models",
        lambda: frozenset({"ghosts.Ghost"}),
    )
    monkeypatch.setattr("apps.separability.registry.pii_fields_for", lambda label: ())

    # E001 also fires (every real model now reads as unregistered); E002 is the point.
    assert "separability.E002" in _ids(checks.check_pii_registry_is_complete(None))


def test_pii_registration_naming_a_dropped_column_is_an_error(monkeypatch):
    """A renamed column leaves the old name mapped and the new one unmapped."""
    from apps.encryption.registry import PiiField

    label = _pii_models()[0]._meta.label
    bogus = PiiField(label, "column_that_does_not_exist", "makerspace_id", None, "source", "none")
    real = {lbl: pii_fields_for(lbl) for lbl in registered_pii_models()}
    real[label] = real[label] + (bogus,)
    monkeypatch.setattr("apps.separability.registry.pii_fields_for", lambda l: real.get(l, ()))
    monkeypatch.setattr("apps.separability.registry.registered_pii_models", lambda: frozenset(real))

    errors = checks.check_pii_registry_is_complete(None)

    assert "separability.E003" in _ids(errors)


def test_purge_plan_for_an_unknown_module_is_an_error(monkeypatch):
    monkeypatch.setattr(
        "apps.separability.registry.registered_purge_modules",
        lambda: frozenset({"not_a_real_module"}),
    )
    assert "separability.E004" in _ids(checks.check_purge_registry_is_complete(None))


def test_a_module_cannot_be_both_purgeable_and_not_separable(monkeypatch):
    """NOT_SEPARABLE says the graph cannot be split; a plan says it can. One is wrong."""
    monkeypatch.setattr(
        "apps.separability.registry.registered_purge_modules",
        lambda: frozenset({"machines"}),
    )
    assert "separability.E005" in _ids(checks.check_purge_registry_is_complete(None))


def test_unfinalized_registries_are_an_error(monkeypatch):
    monkeypatch.setattr("apps.separability.registry.is_finalized", lambda: False)
    assert "separability.E006" in _ids(checks.check_registries_are_frozen(None))


# --------------------------------------------------------------------------
# Registry mechanics (B2).
# --------------------------------------------------------------------------

def test_registration_after_finalisation_is_refused():
    """A late registration is a map some consumers read before it existed."""
    with pytest.raises(RegistryError, match="frozen"):
        register_pii_fields("late.Model", ({"field_name": "x"},))


def test_duplicate_registration_is_fatal_not_last_write_wins():
    from apps.separability.registry import _Registry

    registry = _Registry("test")
    registry.register("k", 1)
    with pytest.raises(RegistryError, match="Duplicate"):
        registry.register("k", 2)


def test_empty_pii_registration_is_refused():
    """An empty field set is the fail-OPEN state expressed as a registration.

    The emptiness guard runs before the registry is touched, so this raises the
    empty-set error rather than the frozen-registry one.
    """
    with pytest.raises(RegistryError, match="fails OPEN"):
        register_pii_fields("some.Model", ())


def test_purge_plan_registration_after_finalisation_is_refused():
    with pytest.raises(RegistryError, match="frozen"):
        register_purge_plan("events", object())


# --------------------------------------------------------------------------
# Runtime manifest (B2) — separate from INSTALLED_APPS.
# --------------------------------------------------------------------------

def test_tombstoned_apps_are_inactive_but_still_installed():
    """The distinction is the whole reason the manifest exists."""
    for label in ("printing", "roadmap"):
        assert django_apps.is_installed(f"apps.{label}"), "migrations must stay applied"
        assert runtime_active(label) is False


def test_unregistered_apps_default_to_active():
    """An app with no tombstone story must not silently lose its surfaces."""
    assert runtime_active("machines") is True
    assert runtime_active("an_app_that_never_registered") is True


def test_every_registered_purge_module_is_a_real_module_key():
    from apps.makerspaces.module_registry import MODULES

    assert registered_purge_modules() <= {definition.key for definition in MODULES}


# --------------------------------------------------------------------------
# The fail-closed backstop, proven at the write boundary.
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_unmapped_model_save_fails_closed_and_writes_nothing(settings, monkeypatch):
    """With encryption on and the registration gone, the write must refuse.

    Without the backstop this same call takes the plain-save branch and stores the
    value in the clear, returning normally — the exact failure the check exists to
    make impossible.
    """
    from apps.integrations.models import EmailLog

    settings.PII_ENCRYPTION_ENABLED = True
    monkeypatch.setattr("apps.encryption.mappers.fields_for", lambda instance: ())

    before = EmailLog.objects.count()
    with pytest.raises(UnmappedPiiModel):
        EmailLog(to_email="leak@example.com", subject="s", stream="account", event="x").save()

    assert EmailLog.objects.count() == before
    assert not EmailLog.objects.filter(to_email="leak@example.com").exists()
