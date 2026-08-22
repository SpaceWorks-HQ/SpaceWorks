"""Deployment-level archive-custody readiness summary."""

from .custody_alarms import readiness_counts


def archive_custody_readiness():
    return readiness_counts()
