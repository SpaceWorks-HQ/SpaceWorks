"""Two explicitly separate recipient sets for Lane D envelopes."""

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.backup.recipients import canonical_recipient

from .tenant_dump_errors import TenantDumpCustodyError


@dataclass(frozen=True)
class TenantDumpRecipientSets:
    outer_recipients: tuple[str, ...]
    tenant_dek_recipients: tuple[str, ...]


def recipient_sets(capture, frozen_tenant_recipients):
    """Derive envelope recipients without ever promoting the platform to DEK custody."""
    try:
        tenant_dek_recipients = tuple(
            item["public_recipient"] for item in frozen_tenant_recipients
        )
    except (KeyError, TypeError):
        raise TenantDumpCustodyError(
            "The frozen Lane D tenant recipient set is invalid."
        ) from None
    if not tenant_dek_recipients or len(tenant_dek_recipients) != len(
        set(tenant_dek_recipients)
    ):
        raise TenantDumpCustodyError(
            "The frozen Lane D tenant recipient set is invalid."
        )
    outer_recipients = tenant_dek_recipients
    configured = settings.BACKUP_AGE_RECIPIENT
    platform_recipient = None
    if configured:
        try:
            platform_recipient = canonical_recipient(configured)
        except ValidationError:
            if capture.superadmin_access_at_decision:
                raise TenantDumpCustodyError(
                    "The Lane D outer platform recipient is invalid."
                ) from None
    if platform_recipient in tenant_dek_recipients:
        raise TenantDumpCustodyError(
            "The Lane D platform and tenant recipient identities overlap."
        )
    if capture.superadmin_access_at_decision:
        if platform_recipient is None:
            raise TenantDumpCustodyError(
                "The Lane D outer platform recipient is not configured."
            )
        outer_recipients = (*outer_recipients, platform_recipient)
    return TenantDumpRecipientSets(
        outer_recipients=outer_recipients,
        tenant_dek_recipients=tenant_dek_recipients,
    )
