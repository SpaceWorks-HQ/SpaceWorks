"""Write platform social sign-in credentials from the command line.

Exists so the first-run wizard has something to call other than a long inline
`shell -c` heredoc, and so an operator who skipped the wizard can configure Google
later without reaching /control/ (which is deliberately not published on the public
frontend port, so a non-technical operator cannot open it).

Only the Google **client IDs** are settable here. There is no client secret to pass:
this is the ID-token flow, and verifying a signature needs only the public JWKS --
the same reason the OIDC provider model stores no secret. Apple needs a private key
file and is left to /control/.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models_social import PlatformSocialAuthSettings


class Command(BaseCommand):
    help = "Configure platform Google sign-in client IDs."

    def add_arguments(self, parser):
        parser.add_argument("--google-web-client-id", default="")
        parser.add_argument("--google-ios-client-id", default="")
        parser.add_argument("--google-android-client-id", default="")
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Remove the stored Google client IDs, disabling Google sign-in.",
        )

    def handle(self, *args, **options):
        fields = {
            "google_web_client_id": options["google_web_client_id"].strip(),
            "google_ios_client_id": options["google_ios_client_id"].strip(),
            "google_android_client_id": options["google_android_client_id"].strip(),
        }
        if options["clear"]:
            fields = dict.fromkeys(fields, "")
        elif not any(fields.values()):
            raise CommandError(
                "Pass at least one --google-*-client-id, or --clear to remove them."
            )

        row = PlatformSocialAuthSettings.load()
        for name, value in fields.items():
            # Only overwrite what was actually supplied, so setting the iOS id later
            # does not wipe the web id an operator configured during setup.
            if value or options["clear"]:
                setattr(row, name, value)
        row.save()

        if options["clear"]:
            self.stdout.write(self.style.WARNING("Google sign-in credentials cleared."))
            return
        self.stdout.write(
            self.style.SUCCESS(
                "Google sign-in configured. It appears on the login screen immediately."
            )
        )
