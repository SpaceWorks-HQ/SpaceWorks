from django.apps import AppConfig


class TenantMigrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenant_migration"

    def ready(self):
        import logging

        from apps.separability.tombstones import register_separable_app

        register_separable_app("tenant_migration")
        from apps.tenant_migration import signals  # noqa: F401

        # Startup cleanup is deliberately conservative: only resources carrying Lane
        # D's ownership marker and older than the configured age are eligible.
        try:
            from .tenant_dump_database_cleanup import sweep_stale_databases
            from .tenant_dump_staging import sweep_stale_staging

            sweep_stale_staging()
            sweep_stale_databases()
        except Exception:
            logging.getLogger(__name__).warning(
                "tenant_dump_startup_sweep_unavailable"
            )
