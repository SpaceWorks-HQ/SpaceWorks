"""Destination lifecycle shared by the API and the control-plane admin."""

import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import offsite_client
from apps.backup.models import BackupDestination


@transaction.atomic
def retire_destination(destination_id, actor):
    destination = BackupDestination.objects.select_for_update().get(pk=destination_id)
    if destination.retired_at is not None:
        raise ValidationError("The destination is already retired.")
    destination.enabled = False
    destination.retired_at = timezone.now()
    destination.set_access_key_id("")
    destination.set_secret_access_key("")
    destination.save()
    audit.record(
        actor, "backup.destination_retired", target=destination,
        meta={"name": destination.name, "archives_outside_purge_guarantee": True},
    )
    return destination


def probe_destination(destination, actor):
    if destination.retired_at is not None:
        raise ValidationError("A retired destination cannot be tested.")
    error_code = ""
    try:
        offsite_client.probe(destination, nonce=uuid.uuid4().hex)
    except offsite_client.OffsiteDestinationError as exc:
        error_code = exc.code
    result = {"ok": not error_code, "error_code": error_code}
    audit.record(actor, "backup.destination_probed", target=destination, meta=result)
    return result
