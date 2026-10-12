"""Shared model/migration checks for append-only replay review metadata."""

from django.db import models


def resolution_constraints():
    return [
        models.CheckConstraint(
            condition=(models.Q(resolution_code__isnull=True, resolved_by__isnull=True,
                                resolved_at__isnull=True, replacement_command__isnull=True)
                       | models.Q(state="failed", resolution_code__isnull=False, resolved_by__isnull=False, resolved_at__isnull=False,
                                  resolution_code="acknowledged_no_change", replacement_command__isnull=True)
                       | models.Q(state="failed", resolution_code__isnull=False, resolved_by__isnull=False, resolved_at__isnull=False,
                                  resolution_code="replaced_online", replacement_command__isnull=False)),
            name="replay_resolution_consistent",
        ),
        models.CheckConstraint(condition=~models.Q(pk=models.F("replacement_command")),
                               name="replay_replacement_not_self"),
        models.UniqueConstraint(fields=("replacement_command",),
                                condition=models.Q(replacement_command__isnull=False),
                                name="replay_replacement_used_once"),
    ]
