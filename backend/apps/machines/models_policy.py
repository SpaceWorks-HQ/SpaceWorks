"""Tenant/type reminder policy; built-in machine types remain global and structural."""

from django.db import models


class MakerspaceMachineTypePolicy(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    machine_type = models.ForeignKey("machines.MachineType", on_delete=models.CASCADE)
    # Null retains the reminder defaults after explicit feature opt-in; zero disables
    # advance notices while overdue/expired notifications remain available.
    cert_reminder_days = models.PositiveSmallIntegerField(null=True, blank=True)
    reminder_lead_days = models.PositiveSmallIntegerField(null=True, blank=True)
    grace_days = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["makerspace", "machine_type"], name="machine_type_policy_unique",
        )]
