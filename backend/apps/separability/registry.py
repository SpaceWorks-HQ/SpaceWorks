"""The two registries that make an app separable (plan B1/B2).

An app can be **tombstoned**: its surfaces disappear, but its rows stay in the
database and its migrations stay installed (`apps/printing` and `apps/roadmap` are
the existing precedent). That single fact forces two registries, not one, because
the two halves have opposite lifetimes:

* **Retention** — purge nodes, object-storage collectors, PII field mappings and
  historical payment subjects. Registered **always, even when tombstoned**.
  Deregistering these is not a cosmetic loss: retained rows become unpurgeable and
  unencryptable, and private S3 objects leak permanently because nothing is left
  that knows their keys.

* **Runtime** — URLs, reports, admin registration, frontend surfaces, origin-scope
  route metadata and live workflow hooks. Registered **only while the app is
  active**, because these are exactly the surfaces a tombstone must remove.

Registration happens in each app's ``AppConfig.ready()``. ``ready()`` also runs for
``migrate``, ``makemigrations``, tests, Celery workers and management commands, so a
registration callback must be **query-free, idempotent and free of schema
assumptions** — it may not touch the database.

Consumers must call the accessor functions in this module rather than importing a
collection once. A module-level ``ALL_FIELDS``/``BY_MODEL``-style import binds a
snapshot taken at import time, which silently goes stale the moment registration
order changes — the class of bug this indirection exists to remove.
"""

from dataclasses import dataclass, field


class RegistryError(RuntimeError):
    """Raised for a registration mistake that must never reach runtime."""


@dataclass
class _Registry:
    """A frozen-after-finalisation keyed collection.

    Duplicate keys are fatal rather than last-write-wins: two apps silently
    claiming the same purge node or PII model means one of them is not being
    purged or encrypted, and the loser is invisible.
    """

    name: str
    _entries: dict = field(default_factory=dict)
    _frozen: bool = False

    def register(self, key, value):
        if self._frozen:
            raise RegistryError(
                f"{self.name} registry is frozen; {key!r} was registered after "
                "finalisation. Register from AppConfig.ready(), not at call time."
            )
        if key in self._entries:
            raise RegistryError(
                f"{self.name} registry already has {key!r}. Duplicate registration "
                "means one of the two owners is silently inactive."
            )
        self._entries[key] = value

    def freeze(self):
        self._frozen = True

    def reset(self):
        """Test-only: return to a mutable, empty state."""
        self._entries = {}
        self._frozen = False

    @property
    def frozen(self):
        return self._frozen

    def get(self, key, default=None):
        return self._entries.get(key, default)

    def keys(self):
        return frozenset(self._entries)

    def items(self):
        return tuple(self._entries.items())

    def values(self):
        return tuple(self._entries.values())


# Retention — survives tombstoning.
_pii_fields = _Registry("PII field")
_purge_plans = _Registry("purge plan")

# Runtime — present only while the owning app is active.
_runtime_apps = _Registry("runtime app")

_finalized = False


# --------------------------------------------------------------------------
# Registration (called from AppConfig.ready(); query-free and idempotent)
# --------------------------------------------------------------------------

def register_pii_fields(model_label, fields):
    """Declare the scoped-PII fields of one model.

    Keyed by model label rather than app label: the completeness check asks
    "does this model have a mapping?", and an app-keyed registry could not answer
    that for an app owning several PII models.
    """
    if not fields:
        raise RegistryError(
            f"{model_label} registered an empty PII field set. A ScopedPiiModelMixin "
            "subclass with no mapped fields fails OPEN and stores plaintext; omit the "
            "mixin instead."
        )
    _pii_fields.register(model_label, tuple(fields))


def register_purge_plan(module_key, plan):
    _purge_plans.register(module_key, plan)


def register_runtime_app(app_label, *, tombstoned=False):
    """Declare an app's runtime surfaces as active (or explicitly tombstoned).

    This is the manifest that replaces ``django.apps.apps.is_installed()``. A
    tombstoned app is still in ``INSTALLED_APPS`` — it must be, or its migrations
    unapply — so ``is_installed()`` answers a question nobody is asking.
    """
    _runtime_apps.register(app_label, not tombstoned)


# --------------------------------------------------------------------------
# Accessors — always call these; never bind the collections above
# --------------------------------------------------------------------------

def pii_fields_for(model_label):
    return _pii_fields.get(model_label, ())


def registered_pii_models():
    return _pii_fields.keys()


def all_pii_fields():
    return tuple(f for fields in _pii_fields.values() for f in fields)


def purge_plan_for(module_key):
    return _purge_plans.get(module_key)


def registered_purge_modules():
    return _purge_plans.keys()


def runtime_active(app_label):
    """True when the app's runtime surfaces should be present.

    Unregistered means active: an app that never opted into separability has no
    tombstone story, and defaulting it to inactive would silently remove working
    surfaces.
    """
    return _runtime_apps.get(app_label, True)


def finalize():
    """Freeze every registry. Called once, after all AppConfig.ready() have run."""
    global _finalized
    _pii_fields.freeze()
    _purge_plans.freeze()
    _runtime_apps.freeze()
    _finalized = True


def is_finalized():
    return _finalized


def reset_for_tests():
    global _finalized
    _pii_fields.reset()
    _purge_plans.reset()
    _runtime_apps.reset()
    _finalized = False
