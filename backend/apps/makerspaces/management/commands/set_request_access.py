"""Set who may submit borrow requests, and report the policy that actually resulted.

Called by `setup.sh` AFTER the module tick list has been applied, never before: the
answer to "who can submit?" is only partly this flag, and the rest is the `membership`
module the operator may have just ticked. Deriving the answer from the live row is what
keeps the installer from reporting a policy the database does not have.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.makerspaces.management.commands.list_modules import resolve_makerspace
from apps.makerspaces.request_access import (
    ACCOUNTS,
    ANYONE,
    MEMBERS,
    POLICY_LABELS,
    RequestAccessConflict,
    effective_policy,
    set_anonymous_requests,
)

MODES = (MEMBERS, ACCOUNTS, ANYONE)


class Command(BaseCommand):
    help = "Set who may submit borrow requests for a makerspace."

    def add_arguments(self, parser):
        parser.add_argument("--makerspace", default=None, help="Makerspace slug (default: the only one).")
        parser.add_argument(
            "--mode",
            required=True,
            choices=MODES,
            help=(
                "members = active members only (requires the membership module); "
                "accounts = any signed-in account; anyone = no account needed."
            ),
        )

    def handle(self, *args, **options):
        makerspace = resolve_makerspace(options["makerspace"])
        mode = options["mode"]
        try:
            # Only `anyone` is a request to OPEN the flag. `members` and `accounts` are
            # both "an account is required", and which of the two you get is decided by
            # the membership module, not by this command -- so both close the flag and
            # then report what the module state actually produced.
            resulting = set_anonymous_requests(makerspace, mode == ANYONE)
        except RequestAccessConflict as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Borrow requests for {makerspace.slug}: {POLICY_LABELS[resulting]}."
            )
        )
        if resulting != mode:
            # Never silently: asking for `members` on a space without the membership
            # module leaves submission open to any signed-in account, and an operator
            # who is not told that believes they closed something they did not.
            self.stdout.write(
                self.style.WARNING(
                    f"You asked for '{mode}' but the live module state produces "
                    f"'{resulting}'. "
                    + (
                        "Install the `membership` module to restrict submission to "
                        "members."
                        if resulting == ACCOUNTS
                        else "Uninstall the `membership` module to allow account-less "
                        "requests."
                    )
                )
            )
        return None


def current_policy(makerspace) -> str:
    """Shared with the installer's read-back step."""
    return effective_policy(makerspace)
