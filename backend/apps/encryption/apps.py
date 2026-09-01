from django.apps import AppConfig


class EncryptionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.encryption"

    def ready(self):
        # Registers the enabled-mode wrapping-configuration system check. The
        # check itself no-ops when PII_ENCRYPTION_ENABLED is False, so importing
        # it here never parses key material in a dormant install.
        from apps.encryption import checks  # noqa: F401
        from apps.encryption import signals  # noqa: F401

        self._register_pii_fields()
        # Celery workers do not use the HTTP readiness view.  The signal keeps an
        # enabled worker from accepting generation-bound tasks before its DB/key
        # preflight passes; disabled installs still do no key parsing or DB work.
        try:
            from celery.signals import worker_process_init
        except ImportError:
            return

        @worker_process_init.connect(weak=False)
        def _pii_worker_readiness(**kwargs):
            from django.conf import settings
            if settings.PII_ENCRYPTION_ENABLED:
                from apps.encryption.readiness import assert_ready
                assert_ready()

    def _register_pii_fields(self):
        """Publish the scoped-PII map into the separability registry.

        The declarations still live in ``encryption/registry.py``. Phase 7 moves the
        *lookup* behind an accessor so nothing can bind a stale snapshot, and puts a
        completeness check in front of it; relocating each app's declarations into
        the app itself happens as that app is made separable (plan B6), because the
        move is only meaningful once an app can actually be tombstoned.

        Query-free and idempotent, as ready() requires: it reads module-level tuples
        and touches no database. Re-registration is skipped rather than fatal so a
        test process that reloads app configs does not trip the duplicate-key rule.
        """
        from apps.encryption.registry import BY_MODEL
        from apps.separability.registry import register_pii_fields, registered_pii_models

        already = registered_pii_models()
        for model_label, fields in BY_MODEL.items():
            if model_label not in already:
                register_pii_fields(model_label, fields)
