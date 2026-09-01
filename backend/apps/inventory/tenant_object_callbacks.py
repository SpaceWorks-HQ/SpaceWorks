"""Source-gated object mutations that run after a database commit."""

import logging

from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.gate_runtime import tenant_write


logger = logging.getLogger(__name__)


def release_public_image(makerspace, object_key, storage=None):
    from apps.inventory import public_image_storage

    try:
        with tenant_write(makerspace.pk):
            public_image_storage.release_public_image(
                makerspace, object_key, storage
            )
    except SourceMigrationGateClosed:
        logger.info(
            "public_image_release_skipped_closed_source_gate",
            extra={"makerspace_id": makerspace.pk, "object_key": object_key},
        )


def delete_public_image(makerspace_id, object_key):
    from apps.inventory import public_image_storage

    try:
        with tenant_write(makerspace_id):
            public_image_storage.delete_object(object_key)
    except SourceMigrationGateClosed:
        logger.info(
            "public_image_delete_skipped_closed_source_gate",
            extra={"makerspace_id": makerspace_id, "object_key": object_key},
        )
