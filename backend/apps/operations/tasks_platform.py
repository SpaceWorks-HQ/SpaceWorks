"""Deployment monitoring writes only a disposable, non-tenant cache marker."""

from celery import shared_task
from django.core.cache import cache

from apps.operations.platform_problems import run_problem_checks

PROBLEM_RUN_CACHE_KEY = "platform:problem-check-run"


@shared_task
def run_platform_problem_checks_task():
    snapshot = run_problem_checks()
    # Keep no tenant identities/results in the cache: hiding a tenant takes effect
    # immediately on every API read, even after this scheduled run.
    summary = {"checked_at": snapshot["checked_at"].isoformat(),
               "status": snapshot["status"]}
    cache.set(PROBLEM_RUN_CACHE_KEY, summary, timeout=3600)
    return summary
