from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        # D2 owns the single transition hook registry. D4 registers claim-code
        # revocation into it; D5 will extend this same hook with live-session cleanup.
        from apps.accounts.services_claim import register_transition_revocation

        register_transition_revocation()
