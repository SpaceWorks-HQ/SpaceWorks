"""Public inventory statistics assembled only from canonical models."""

from apps.inventory.public_stats_hardware import (
    current_loans as _current_loans,
    hardware_stats as _hardware_stats,
)
from apps.makerspaces.platform import module_enabled
from apps.machines.public_printer_stats import build_public_printer_stats
from apps.machines.public_stats import build_public_machine_stats


def build_public_stats(makerspace) -> dict:
    return {
        "machines": build_public_machine_stats(makerspace),
        "printing": _printing_stats(makerspace),
        "hardware": _hardware_stats(makerspace),
        "current_loans": _current_loans(makerspace),
    }


def _printing_stats(makerspace):
    if not (
        module_enabled(makerspace, "machine_service")
        and module_enabled(makerspace, "printing")
    ):
        return None
    return build_public_printer_stats(makerspace)
