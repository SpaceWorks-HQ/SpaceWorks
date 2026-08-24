"""Install carried DEKs under the target deployment's configured key broker."""

from apps.encryption import services
from apps.encryption.models import MakerspaceEncryptionKey

from .insertion_errors import ArchiveFormatError


def install_carried_deks(makerspace, carried_keys):
    """Legacy archive adapter; Lane D calls the streaming primitive in its child."""
    return install_streamed_deks(
        makerspace,
        sorted(carried_keys, key=lambda item: item["version"]),
        preserved_makerspace_id=makerspace.pk,
    )


def install_streamed_deks(makerspace, carried_keys, *, preserved_makerspace_id):
    """Wrap an iterator of plaintext records without materializing that iterator."""
    if preserved_makerspace_id != makerspace.pk:
        raise ArchiveFormatError(
            "The target makerspace id must preserve the source encryption identity."
        )
    broker = services.configured_broker()
    installed = []
    seen = set()
    for record in carried_keys:
        version = int(record["version"])
        if version in seen or version < 1:
            raise ArchiveFormatError("Carried DEK versions must be unique and positive.")
        seen.add(version)
        if record.get("insert_at_target", True) is False:
            continue
        status = record.get("status")
        if status not in {
            MakerspaceEncryptionKey.Status.ACTIVE,
            MakerspaceEncryptionKey.Status.ROTATED,
        }:
            raise ArchiveFormatError("Only ACTIVE or ROTATED carried DEKs may be installed.")
        try:
            dek = record["dek"]
            wrapped = broker.wrap_dek(dek, makerspace.pk, version)
        except (KeyError, TypeError, ValueError) as exc:
            raise ArchiveFormatError("A carried DEK record is incomplete.") from exc
        MakerspaceEncryptionKey.objects.create(
            makerspace=makerspace,
            version=version,
            wrapped_dek=wrapped.wrapped_dek,
            broker_backend=broker.backend,
            broker_key_id=wrapped.broker_key_id,
            status=status,
        )
        installed.append(version)
    active = MakerspaceEncryptionKey.objects.filter(
        makerspace=makerspace,
        status=MakerspaceEncryptionKey.Status.ACTIVE,
    ).count()
    if active != 1:
        raise ArchiveFormatError("The target must receive exactly one active DEK.")
    return tuple(installed)
