"""Eager key provisioning for makerspaces created after the install cutover."""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.audit.keys import (
    AuditMacKeyUnavailable,
    audit_mac_configured,
    provision_audit_mac_key,
)
from apps.makerspaces.models import Makerspace

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Makerspace, dispatch_uid="audit.provision_mac_key")
def provision_makerspace_audit_mac_key(sender, instance, created, raw, **kwargs):
    # audit_mac_configured() must gate this: with AUDIT_MAC_MASTER_KEY unset (the
    # opt-out default) provision_audit_mac_key -> _fernet() raises ImproperlyConfigured,
    # which would make EVERY makerspace creation fail -- and under autocommit the row may
    # already be persisted when the caller sees the error.
    if created and not raw and audit_mac_configured():
        try:
            provision_audit_mac_key(instance.pk)
        except AuditMacKeyUnavailable:
            # A malformed master key must not make makerspace creation impossible; the
            # startup check reports it and rows are written honestly unattested.
            logger.critical(
                "audit_mac_key_provisioning_failed",
                extra={"makerspace_id": instance.pk},
            )
