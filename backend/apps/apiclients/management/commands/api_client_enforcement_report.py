from django.core.management.base import BaseCommand

from apps.apiclients.models import ApiClient
from apps.apiclients.scope_registry import LEGACY_SCOPE, SCOPE_VOCABULARY


class Command(BaseCommand):
    help = "Report API clients that are not ready for staged auth enforcement."

    def handle(self, *args, **options):
        clients = list(ApiClient.objects.order_by("client_id"))
        legacy = [client for client in clients if LEGACY_SCOPE in _scopes(client)]
        no_origins = [client for client in clients if not client.allowed_origins]
        outside_vocabulary = [
            (client, sorted(set(_scopes(client)) - SCOPE_VOCABULARY))
            for client in clients
            if set(_scopes(client)) - SCOPE_VOCABULARY
        ]

        self.stdout.write("API client enforcement readiness")
        self.stdout.write(f"total_clients={len(clients)}")
        self._write_clients("legacy:v1", legacy)
        self._write_clients("no_allowed_origins", no_origins)
        self.stdout.write(f"unknown_scopes={len(outside_vocabulary)}")
        for client, unknown in outside_vocabulary:
            self.stdout.write(
                f"  {_identity(client)} scopes={','.join(unknown)}"
            )

    def _write_clients(self, heading, clients):
        self.stdout.write(f"{heading}={len(clients)}")
        for client in clients:
            self.stdout.write(f"  {_identity(client)}")


def _scopes(client):
    if not isinstance(client.scopes, list):
        return [f"<invalid-{type(client.scopes).__name__}>"]
    return [scope if isinstance(scope, str) else repr(scope) for scope in client.scopes]


def _identity(client):
    return f"client_id={client.client_id} label={client.label}"
