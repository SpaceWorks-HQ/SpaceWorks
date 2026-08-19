from django.apps import AppConfig


class ApiClientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.apiclients"

    def ready(self):
        from apps.apiclients import checks  # noqa: F401
