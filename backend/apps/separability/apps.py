from django.apps import AppConfig


class SeparabilityConfig(AppConfig):
    """Finalises the separability registries and installs the completeness checks.

    This app owns no models and no migrations; it exists purely to be the last
    ``ready()`` to run. Django populates the app registry in two passes — every
    models module is imported first, then every ``ready()`` is called in
    ``INSTALLED_APPS`` order — so being listed last is what guarantees that every
    other app has finished registering before ``finalize()`` freezes the maps.

    Freezing matters because a registration arriving after this point would be a
    map that some consumers read before the entry existed and others after, which
    is precisely the stale-snapshot problem the accessor functions exist to prevent.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.separability"

    def ready(self):
        from apps.separability import checks  # noqa: F401  (registers the checks)
        from apps.separability.registry import finalize, is_finalized

        # ready() can run more than once in a test process that reloads app configs;
        # finalize() is idempotent, but guard anyway so the intent is explicit.
        if not is_finalized():
            finalize()
