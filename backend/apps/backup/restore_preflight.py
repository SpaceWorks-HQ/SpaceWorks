"""Compatibility surface for the preflight split introduced by K2.

The Lane E9b implementation remains in :mod:`backup_control_preflight`, where it
routes legacy and compound archives through their distinct fail-closed validators.
"""

from apps.backup.backup_control_preflight import run_restore_preflight


run_preflight = run_restore_preflight

__all__ = ("run_preflight", "run_restore_preflight")
