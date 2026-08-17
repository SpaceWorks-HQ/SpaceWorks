from django.apps import AppConfig


class TenantMigrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenant_migration"

    def ready(self):
        from apps.separability.tombstones import register_separable_app

        register_separable_app("tenant_migration")
        from apps.tenant_migration import signals  # noqa: F401
