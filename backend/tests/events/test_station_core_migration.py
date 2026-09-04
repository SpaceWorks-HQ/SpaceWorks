from datetime import timedelta
from uuid import uuid4
import hashlib
import hmac

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from apps.makerspaces.module_registry import default_enabled_module_keys
from rest_framework.exceptions import PermissionDenied

from apps.apiclients.crypto import encrypt_secret


pytestmark = pytest.mark.django_db(transaction=True)


def test_event_station_credentials_copy_losslessly_and_reverse(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")
    settings.EVENT_STATION_PIN_PEPPER = "migration-test-event-station-pepper"
    from_target = [
        ("events", "0022_event_search_vector"),
        ("makerspaces", "0072_enable_charge_tracking_for_existing_makerspaces"),
    ]
    target = [
        ("events", "0023_event_station_binding"),
        ("makerspaces", "0073_shared_station"),
    ]
    executor = MigrationExecutor(connection)
    snapshots = []

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        Makerspace = old_apps.get_model("makerspaces", "Makerspace")
        Event = old_apps.get_model("events", "Event")
        OldCredential = old_apps.get_model(
            "events", "EventCheckInStationCredential"
        )
        space = Makerspace.objects.create(
            name="Station migration",
            slug="station-migration",
            # `events` is an OPTIONAL module, so it is absent from the JSONField default a
            # historical model still applies -- and `events.offline_checkin` resolves through
            # its parent module, so rotate() would refuse the feature without this.
            enabled_modules=sorted({*default_enabled_module_keys(), "events"}),
            enabled_features=["events.offline_checkin"],
        )
        now = timezone.now()
        for index, enabled in enumerate((True, False), start=1):
            event = Event.objects.create(
                makerspace_id=space.pk,
                title=f"Station migration {index}",
                status="published",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=1),
                is_public=True,
            )
            pin = f"{index:08d}"
            version = index + 2
            message = (
                f"spaceworks:event-station-pin:v1:{event.pk}:{version}:{pin}"
            ).encode()
            material = hmac.new(
                settings.EVENT_STATION_PIN_PEPPER.encode(),
                message,
                hashlib.sha256,
            ).hexdigest()
            created_at = now - timedelta(days=index)
            updated_at = created_at + timedelta(minutes=5)
            token = uuid4()
            ciphertext = encrypt_secret(pin)
            row = OldCredential.objects.create(
                event_id=event.pk,
                public_token=token,
                pin_digest=make_password(material),
                pin_ciphertext=ciphertext,
                version=version,
                is_enabled=enabled,
                rotated_at=created_at,
                disabled_at=None if enabled else updated_at,
            )
            OldCredential.objects.filter(pk=row.pk).update(
                created_at=created_at,
                updated_at=updated_at,
            )
            snapshots.append({
                "event_id": event.pk,
                "pin": pin,
                "public_token": token,
                "pin_digest": row.pin_digest,
                "pin_ciphertext": bytes(ciphertext),
                "version": version,
                "is_enabled": enabled,
                "rotated_at": created_at,
                "disabled_at": None if enabled else updated_at,
                "created_at": created_at,
                "updated_at": updated_at,
            })

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        Station = new_apps.get_model("makerspaces", "Station")
        Credential = new_apps.get_model("makerspaces", "StationCredential")
        Binding = new_apps.get_model("events", "EventStationBinding")
        for snapshot in snapshots:
            binding = Binding.objects.get(event_id=snapshot["event_id"])
            station = Station.objects.get(pk=binding.station_id)
            credential = Credential.objects.get(station_id=station.pk)
            assert station.makerspace_id == space.pk
            assert station.kind == "event_checkin"
            assert station.name == f"event-{snapshot['event_id']}"
            assert station.created_by_id is None
            assert station.created_at == snapshot["created_at"]
            assert station.updated_at == snapshot["updated_at"]
            assert binding.created_at == snapshot["created_at"]
            for field in (
                "public_token", "pin_digest", "version", "is_enabled",
                "rotated_at", "disabled_at", "created_at", "updated_at",
            ):
                assert getattr(credential, field) == snapshot[field]
            assert bytes(credential.pin_ciphertext) == snapshot["pin_ciphertext"]

        from apps.events.services_station import start_session, station_url

        enabled = snapshots[0]
        event, credential, _session_id, _cookie, _expires_at = start_session(
            enabled["public_token"], pin=enabled["pin"]
        )
        assert credential.public_token == enabled["public_token"]
        assert station_url(event, credential.public_token).endswith(
            f"/event-check-in/{enabled['public_token']}"
        )
        with pytest.raises(PermissionDenied):
            start_session(snapshots[1]["public_token"], pin=snapshots[1]["pin"])

        executor = MigrationExecutor(connection)
        executor.migrate(from_target)
        reversed_apps = executor.loader.project_state(from_target).apps
        Restored = reversed_apps.get_model(
            "events", "EventCheckInStationCredential"
        )
        for snapshot in snapshots:
            restored = Restored.objects.get(event_id=snapshot["event_id"])
            for field in (
                "public_token", "pin_digest", "version", "is_enabled",
                "rotated_at", "disabled_at", "created_at", "updated_at",
            ):
                assert getattr(restored, field) == snapshot[field]
            assert bytes(restored.pin_ciphertext) == snapshot["pin_ciphertext"]
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
