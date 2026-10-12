"""Purge immutable receipt children before their label parents, no storage work."""
from apps.makerspaces.module_purge_collectors_single_model import _counts, _delete


def delete_label_commands(makerspace):
    from apps.devices.models import LabelPrintCommand, LabelPrintResult

    receipts, receipt_labels = _delete(LabelPrintResult.objects.filter(makerspace=makerspace))
    labels, label_models = _delete(LabelPrintCommand.objects.filter(makerspace=makerspace))
    return _counts(model_labels=receipt_labels | label_models,
                   label_result_receipts=receipts, label_print_commands=labels)
