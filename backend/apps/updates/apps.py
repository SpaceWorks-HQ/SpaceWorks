from django.apps import AppConfig


class UpdatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.updates"

    def ready(self):
        from apps.separability.tombstones import register_separable_app

        register_separable_app("updates")
