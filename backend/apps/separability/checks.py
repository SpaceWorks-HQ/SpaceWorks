"""Registry-completeness checks that fail startup rather than surface at runtime (plan B3).

Both gaps this guards against fail **OPEN**, which is why they cannot be left to a
runtime assertion:

* **A missing PII registration silently stores plaintext.** ``ScopedPiiModelMixin``
  asks the registry for a model's mapped fields and treats an empty answer as
  "this model holds no PII". Every protection then no-ops in the safe-looking
  direction: ``__getattribute__`` returns the raw column, the ``bulk_create`` guard
  passes, the save boundary writes no envelope and the write fence is skipped. The
  row is written in the clear and nothing raises.

* **A missing purge registration leaks private object storage permanently.** Purge
  collects S3 keys from the plan; a module with no plan contributes no keys, the
  rows go and the objects stay, with nothing left that knows their keys.

Both are invisible in normal use and only observable by inspecting the database or
the bucket — so the only safe failure mode is refusing to start.
"""

from django.core.checks import Error, Tags, register


def _pii_models():
    """Every concrete model that opted into the scoped-PII boundary."""
    from django.apps import apps as django_apps

    from apps.encryption.mappers import ScopedPiiModelMixin

    return [
        model
        for model in django_apps.get_models()
        if issubclass(model, ScopedPiiModelMixin) and not model._meta.abstract
    ]


@register(Tags.models)
def check_pii_registry_is_complete(app_configs, **kwargs):
    """Every mapped model must declare fields, and every declaration must resolve.

    Deliberately **not** gated on ``PII_ENCRYPTION_ENABLED``. A deployment that has
    not enabled encryption yet is exactly the one that will enable it later, and the
    gap has to be caught before the switch is flipped — not at the moment it starts
    silently writing plaintext into a mapped column.
    """
    from django.apps import apps as django_apps

    from apps.separability.registry import pii_fields_for, registered_pii_models

    errors = []

    for model in _pii_models():
        if not pii_fields_for(model._meta.label):
            errors.append(
                Error(
                    f"{model._meta.label} inherits ScopedPiiModelMixin but has no PII "
                    "field registration.",
                    hint=(
                        "An unregistered mapped model fails OPEN: writes skip "
                        "encryption and the write fence, and store plaintext. Register "
                        "its fields, or drop the mixin if the model holds no PII."
                    ),
                    id="separability.E001",
                )
            )

    for label in registered_pii_models():
        try:
            model = django_apps.get_model(label)
        except (LookupError, ValueError):
            errors.append(
                Error(
                    f"PII fields are registered for {label!r}, which is not a model.",
                    hint="A stale label registers protection for nothing.",
                    id="separability.E002",
                )
            )
            continue
        declared = {f.field_name for f in pii_fields_for(label)}
        actual = {f.name for f in model._meta.get_fields() if hasattr(f, "attname")}
        missing = sorted(declared - actual)
        if missing:
            errors.append(
                Error(
                    f"{label} registers PII fields that do not exist: {', '.join(missing)}.",
                    hint="A renamed column leaves its old name mapped and the new one unmapped.",
                    id="separability.E003",
                )
            )

    return errors


@register(Tags.models)
def check_purge_registry_is_complete(app_configs, **kwargs):
    """Every purge plan must name a real module, and claim a real reason to exist."""
    from apps.makerspaces.module_purge_plans import NOT_SEPARABLE
    from apps.makerspaces.module_registry import MODULES
    from apps.separability.registry import registered_purge_modules

    known = {definition.key for definition in MODULES}
    errors = []

    for key in registered_purge_modules():
        if key not in known:
            errors.append(
                Error(
                    f"A purge plan is registered for unknown module {key!r}.",
                    hint="Module keys come from module_registry.MODULES.",
                    id="separability.E004",
                )
            )

    overlap = sorted(registered_purge_modules() & set(NOT_SEPARABLE))
    if overlap:
        errors.append(
            Error(
                f"Modules both purgeable and marked NOT_SEPARABLE: {', '.join(overlap)}.",
                hint="NOT_SEPARABLE states the data cannot be purged in isolation; a plan says it can.",
                id="separability.E005",
            )
        )

    return errors


@register(Tags.models)
def check_tombstones_are_legal(app_configs, **kwargs):
    """Refuse to tombstone an app that was never made separable.

    One rule covers three mistakes that look identical from the outside, because all
    three produce a setting that reads as a working tombstone and does nothing:

    * an app owning a **core** module, whose surfaces the rest of the system needs --
      the Hard Rules require a box QR scan and an issue photo to hand hardware over,
      so evidence and QR cannot be removed. Tombstoning those would not yield a
      smaller install, it would yield a broken one, discovered as scattered 404s;
    * an app nobody has done the separability work for, whose surfaces would stay
      wired and whose retention hooks were never checked;
    * a typo, or the dotted path where the label belongs.

    Silence is the dangerous outcome here, not over-strictness: a rejected label costs
    one startup, an accepted-but-inert one costs a deployment that believes it removed
    an app it is still serving.
    """
    from django.conf import settings

    from apps.separability.tombstones import SEPARABLE_APPS

    illegal = sorted(set(getattr(settings, "TOMBSTONED_APPS", frozenset())) - SEPARABLE_APPS)
    return [
        Error(
            f"TOMBSTONED_APPS names {label!r}, which is not a separable app.",
            hint=(
                "Separable apps are "
                f"{', '.join(sorted(SEPARABLE_APPS))}. Use the app label, not the "
                "module key or the dotted path, and add the app to SEPARABLE_APPS "
                "only once its surfaces are actually gated."
            ),
            id="separability.E007",
        )
        for label in illegal
    ]


@register(Tags.models)
def check_registries_are_frozen(app_configs, **kwargs):
    """Finalisation must have run, or late registration can still mutate the map."""
    from apps.separability.registry import is_finalized

    if not is_finalized():
        return [
            Error(
                "Separability registries were never finalised.",
                hint=(
                    "SeparabilityConfig.ready() calls finalize(). If it did not run, "
                    "apps.separability is missing from INSTALLED_APPS or is not listed last."
                ),
                id="separability.E006",
            )
        ]
    return []
