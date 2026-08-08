from django.apps import AppConfig


class WarrantyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.warranty"

    def ready(self):
        from apps.separability.tombstones import register_separable_app

        register_separable_app("warranty")
        # Retention, not runtime: the receiver removes the private warranty document
        # from storage on every delete path, purge included. It must stay connected
        # while tombstoned or the bucket keeps objects nothing can name.
        from apps.warranty import signals  # noqa: F401  (registers post_delete receiver)
