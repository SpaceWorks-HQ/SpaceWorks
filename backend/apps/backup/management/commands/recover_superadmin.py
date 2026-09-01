import secrets

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.backup.recovery import set_recovery_principal


class Command(BaseCommand):
    help = "Recover one existing superadmin as the durable out-of-band quarantine principal."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--password", help="Use an explicit password instead of generating one.")

    def handle(self, *args, **options):
        user = User.objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError("The existing superadmin was not found.")
        password = options.get("password") or secrets.token_urlsafe(24)
        try:
            set_recovery_principal(user, password)
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Recovered superadmin: {user.username}")
        self.stdout.write(f"One-time displayed password: {password}")

