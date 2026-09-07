"""Reports-module purge collectors: schedules, their deliveries and the delivered files.

Metric rollups are deliberately NOT here: they are append-only rows behind a retention
fence (`report_rollups.satisfy_retention_fence`), so removing them is a retention decision
the evidence sweep depends on, not a "turn the module off" clean-up. Same two rules as the
other collectors: only what the module owns, model imports function-local.
"""
from apps.makerspaces.module_purge_collectors_single_model import _counts, _delete


def reports_private_keys(makerspace, add):
    """Delivered report files: private objects deleted with the module."""
    from apps.operations.models import ReportDelivery

    for key in ReportDelivery.objects.filter(schedule__makerspace=makerspace).exclude(
        object_key=""
    ).values_list("object_key", flat=True):
        add(key)


def reports_delete(makerspace, cursor):
    from apps.operations.models import ReportSchedule

    deleted, labels = _delete(ReportSchedule.objects.filter(makerspace=makerspace))
    return _counts(model_labels=labels, report_schedules=deleted)
