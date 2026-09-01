"""Which machines a role's ``MANAGE_MACHINES`` grant actually reaches.

``MANAGE_MACHINES`` used to be makerspace-wide: holding it meant authority over every
machine in the space, present and future. That is too coarse for a lab where the laser
team and the print team are different people -- granting someone the printers also
granted them the laser cutters, and there was no narrower action to hand out.

These two link tables scope the grant. A role holding ``MANAGE_MACHINES`` reaches a
machine when **its type is linked or the machine itself is linked**; the two are a union,
not a hierarchy, so "all printers, plus that one laser cutter" is expressible without
inventing a third concept.

**No links means no machines.** The mechanism fails closed, which is the only safe
direction: a role that was meant to be scoped but whose links were never created must be
able to touch nothing, not everything. The upgrade path is a backfill migration
(``0020``) that links every existing ``MANAGE_MACHINES`` role to every type that exists
at that moment, so no deployment loses access the day it upgrades -- while a role created
afterwards starts empty and a machine type added afterwards is reached by nobody until
someone grants it.

Two deliberate exemptions, both in ``role_scope.py`` rather than here:
``MANAGE_MAKERSPACE`` covers everything including future types (a space manager who has
to enumerate machine types to keep administering their own lab is a worse failure than
the over-broad grant this replaces), and a membership with a **null** ``assigned_role``
resolves through the frozen legacy fallback, which is not a role row and therefore has
nothing to link -- scoping it would silently strip a legacy Machine Manager.

Tenant integrity is enforced at the write boundary (``role_scope_services``) and again by
resolution, which always ANDs the makerspace. A mislinked row is inert, not a leak.
"""

from django.core.exceptions import ValidationError
from django.db import models


class RoleMachineTypeScope(models.Model):
    """Grants a role authority over every machine of one type in its makerspace.

    Types are the durable unit: a lab buys another printer far more often than it invents
    another category of machine, and a type link means the new printer is covered the
    moment it is registered. Linking a **built-in** (global, ``makerspace=NULL``) type is
    normal and is not cross-tenant -- coverage is still bounded by the machine's own
    makerspace at resolution.
    """

    role = models.ForeignKey(
        "makerspaces.MakerspaceRole",
        on_delete=models.CASCADE,
        related_name="machine_type_scopes",
    )
    machine_type = models.ForeignKey(
        "machines.MachineType",
        on_delete=models.CASCADE,
        related_name="role_scopes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["role", "machine_type"], name="rolemachinetypescope_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.role_id} -> type {self.machine_type_id}"

    def clean(self):
        """Reject a link across makerspaces. A global built-in type is always allowed."""
        machine_type = self.machine_type
        if machine_type.makerspace_id is None:
            return
        if machine_type.makerspace_id != self.role.makerspace_id:
            raise ValidationError(
                {"machine_type": "A role can only be scoped to its own makerspace's machine types."}
            )


class RoleMachineScope(models.Model):
    """Grants a role authority over one specific machine.

    The escape hatch for the case a type link cannot express: one shared machine a
    narrowly-scoped team also needs. Deliberately NOT the primary mechanism -- a lab that
    links machines one by one has to remember to link every new one, and the machine
    nobody remembered is the machine nobody can service.
    """

    role = models.ForeignKey(
        "makerspaces.MakerspaceRole",
        on_delete=models.CASCADE,
        related_name="machine_scopes",
    )
    machine = models.ForeignKey(
        "machines.Machine",
        on_delete=models.CASCADE,
        related_name="role_scopes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["role", "machine"], name="rolemachinescope_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.role_id} -> machine {self.machine_id}"

    def clean(self):
        """Reject a link across makerspaces. Machines are always tenant-owned."""
        if self.machine.makerspace_id != self.role.makerspace_id:
            raise ValidationError(
                {"machine": "A role can only be scoped to its own makerspace's machines."}
            )
