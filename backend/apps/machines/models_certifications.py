"""Training records: which machine types a member has been certified to use.

A makerspace defines a ``CertificationType`` per machine type ("Laser cutter
induction"), and issues a ``CertificationGrant`` to one membership when that member has
been trained. The gate in ``certifications.py`` reads these two tables; nothing else may
compute "is this member certified".

Two deliberate shapes:

- **The requirement lives on the type, not the machine.** Training is about a class of
  hardware, not one serial number, so buying another laser cutter must not silently
  un-gate it. ``is_required_for_service`` and ``is_required_for_booking`` are separate
  flags because the two are genuinely different risks: a staff-operated print job needs
  no member training, while booking the machine to use it yourself does.
- **A grant is never deleted, and never edited into invalidity.** Revocation sets
  ``revoked_at``/``revoked_by`` and expiry is a stored ``expires_at`` rather than a
  recomputation from ``validity_days``, so shortening a type's validity window later
  cannot retroactively invalidate training that was correctly issued under the old
  policy. The grant row is the evidence that someone was trained on a date; a delete
  would erase the accountability trail that justified letting them near the machine.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class CertificationType(models.Model):
    """One training requirement a makerspace defines over one machine type."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="certification_types",
    )
    machine_type = models.ForeignKey(
        "machines.MachineType",
        on_delete=models.CASCADE,
        related_name="certification_types",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # NULL means "never expires". A stored window rather than a policy the gate
    # recomputes: see the module docstring.
    validity_days = models.PositiveIntegerField(null=True, blank=True)
    is_required_for_service = models.BooleanField(default=False)
    is_required_for_booking = models.BooleanField(default=False)
    # Soft-delete. Deactivating stops the gate consulting the type while leaving every
    # issued grant intact, so re-activating does not require re-training everybody.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "machine_type", "name"],
                name="certificationtype_uniq_name",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.machine_type_id})"


class CertificationGrant(models.Model):
    """Records that one membership holds one certification, until revoked or expired."""

    certification_type = models.ForeignKey(
        "machines.CertificationType",
        on_delete=models.CASCADE,
        related_name="grants",
    )
    membership = models.ForeignKey(
        "makerspaces.MakerspaceMembership",
        on_delete=models.CASCADE,
        related_name="certification_grants",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="certifications_granted",
    )
    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="certifications_revoked",
    )
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["membership", "certification_type"],
                name="certgrant_member_type_idx",
            ),
        ]

    def __str__(self):
        return f"{self.membership_id} -> {self.certification_type_id}"

    def is_active(self, now=None):
        """Unrevoked and unexpired at ``now``. The single definition of a live grant."""
        if self.revoked_at is not None:
            return False
        moment = now or timezone.now()
        return self.expires_at is None or self.expires_at > moment
