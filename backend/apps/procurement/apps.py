from django.apps import AppConfig


class ProcurementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.procurement"
    label = "procurement"

    def ready(self):
        from apps.separability.tombstones import register_separable_app

        # Retention, not runtime: the receiver removes the private receipt object
        # from storage on every delete path, including a purge of a tombstoned app.
        # Deregistering it when tombstoned is what would leak the bucket.
        from apps.procurement import signals  # noqa: F401  (registers post_delete receiver)

        register_separable_app("procurement")
