"""Per-event notification recipient selection.

Fills two gaps rather than replacing anything. Recipients are already resolved per
feature by ACTION (`staff_notifications._FEATURE_ACTIONS` → `rbac.actions_for_membership`),
so a custom role holding `manage_events` already receives event alerts. What was missing:

* **per-event** selection for events/bookings/maintenance/members — `role_muted` only ever
  applied to the hardware and printing streams, so those four were all-or-nothing;
* recipients that are not staff at all — the whole member body, or a named individual.

**Absence of rows means today's behaviour, not "nobody".** That is the load-bearing rule:
bookings email and telegram are ON by default in `DEFAULT_CHANNEL_STATE`, so a strict
default-nobody would have silently stopped booking alerts that are flowing right now.
Rows are authoritative only once at least one exists for a (feature, event).

`role` is a real FK, so a renamed role keeps its rules and a deleted role takes its rules
with it — the reason a slug string was rejected. Cross-tenant safety does not rest on the
FK: resolution always ANDs the makerspace, so a row pointing at another space's role
matches nobody rather than leaking.
"""

from django.conf import settings
from django.db import models

from apps.integrations.notification_enums import NotificationFeature


class NotificationRecipientKind(models.TextChoices):
    ROLE = "role", "Role"
    # The person the notification is about (requester, booker, registrant). Not resolvable
    # from (feature, event) alone -- it comes off the domain object -- so this kind is a
    # flag the caller reads, never an address this module produces.
    REQUESTER = "requester", "Requester"
    MEMBERS = "members", "All members"
    USER = "user", "Named user"


class NotificationRecipient(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="notification_recipients",
    )
    feature = models.CharField(max_length=32, choices=NotificationFeature.choices)
    event = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=NotificationRecipientKind.choices)
    role = models.ForeignKey(
        "makerspaces.MakerspaceRole",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notification_recipients",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notification_recipient_rows",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notification_recipients_created",
    )

    class Meta:
        constraints = [
            # The FK must match the kind. Without this a kind="role" row with a null role
            # is a rule that silently matches nobody, and a kind="members" row carrying a
            # role is ambiguous about which one wins.
            models.CheckConstraint(
                condition=(
                    models.Q(kind="role", role__isnull=False, user__isnull=True)
                    | models.Q(kind="user", user__isnull=False, role__isnull=True)
                    | models.Q(
                        kind__in=("requester", "members"),
                        role__isnull=True,
                        user__isnull=True,
                    )
                ),
                name="notification_recipient_kind_matches_target",
            ),
            # Three partial constraints rather than one over all five columns: Postgres
            # treats NULLs as distinct, so a single UniqueConstraint including `role` and
            # `user` would happily accept duplicate requester/members rows.
            models.UniqueConstraint(
                fields=["makerspace", "feature", "event", "kind"],
                condition=models.Q(kind__in=("requester", "members")),
                name="uniq_notification_recipient_special",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "feature", "event", "role"],
                condition=models.Q(role__isnull=False),
                name="uniq_notification_recipient_role",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "feature", "event", "user"],
                condition=models.Q(user__isnull=False),
                name="uniq_notification_recipient_user",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "feature", "event"]),
        ]
        ordering = ["makerspace__name", "feature", "event", "kind"]

    def __str__(self):
        target = self.role_id or self.user_id or self.kind
        return f"{self.makerspace}:{self.feature}/{self.event} -> {target}"


# --- optional per-rule narrowing -------------------------------------------------------
#
# Mirrors the destination scope tables and, before them, `RoleMachineTypeScope` /
# `RoleMachineScope`: link rows, matched as a union, and **no links means everything**.
# Composition is `role_scope AND (rule_scope OR all)`, so these can only ever narrow —
# a rule naming a machine the recipient's role cannot reach yields nobody rather than
# alerting someone about hardware they would 403 on.


class RecipientMachineTypeScope(models.Model):
    recipient = models.ForeignKey(
        NotificationRecipient,
        on_delete=models.CASCADE,
        related_name="machine_type_scopes",
    )
    machine_type = models.ForeignKey(
        "machines.MachineType",
        on_delete=models.CASCADE,
        related_name="notification_recipient_scopes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "machine_type"],
                name="uniq_recipient_machine_type_scope",
            )
        ]


class RecipientMachineScope(models.Model):
    recipient = models.ForeignKey(
        NotificationRecipient,
        on_delete=models.CASCADE,
        related_name="machine_scopes",
    )
    machine = models.ForeignKey(
        "machines.Machine",
        on_delete=models.CASCADE,
        related_name="notification_recipient_scopes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "machine"],
                name="uniq_recipient_machine_scope",
            )
        ]


class RecipientCategoryScope(models.Model):
    recipient = models.ForeignKey(
        NotificationRecipient,
        on_delete=models.CASCADE,
        related_name="category_scopes",
    )
    category = models.ForeignKey(
        "inventory.Category",
        on_delete=models.CASCADE,
        related_name="notification_recipient_scopes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "category"],
                name="uniq_recipient_category_scope",
            )
        ]
