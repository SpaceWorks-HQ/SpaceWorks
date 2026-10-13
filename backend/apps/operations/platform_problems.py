"""Run each declared check independently; failed reads remain visible warnings."""

import logging

from django.utils import timezone

from apps.makerspaces.servability import servable_queryset
from apps.operations.platform_checks import PROBLEM_CHECKS, result
from apps.operations.platform_dashboard import platform_spaces, tenant_check_context
from apps.operations.platform_signals import (
    backup_snapshot, offsite_snapshot, scheduler_snapshot,
)

logger = logging.getLogger(__name__)


def run_problem_checks(actor=None):
    now = timezone.now()
    spaces = list(servable_queryset(platform_spaces(actor)).order_by("id"))
    readers = {
        "backup": backup_snapshot,
        "offsite": lambda: offsite_snapshot([space.pk for space in spaces]),
        "scheduler": lambda: scheduler_snapshot(now),
    }
    results = []
    for check in PROBLEM_CHECKS:
        targets = spaces if check.scope == "tenant" else [None]
        for space in targets:
            try:
                data = tenant_check_context(space, check.key) if space else readers[check.key]()
                results.extend(check.evaluate(data, now))
            except Exception as exc:
                # Provider exception strings may contain credentials. Keep only the
                # type in logs; show a fixed message and a safe local link to users.
                logger.warning("platform_problem_check_unavailable", extra={
                    "check_key": check.key, "error_type": type(exc).__name__,
                })
                results.append(result(check.key, "warn", "This check could not be completed.",
                                      f"/m/{space.slug}/admin/settings" if space else "/admin/platform",
                                      space.pk if space else None))
    severity = "error" if any(r["status"] == "error" for r in results) else (
        "warn" if any(r["status"] == "warn" for r in results) else "ok"
    )
    return {"checked_at": now, "status": severity, "results": results}
