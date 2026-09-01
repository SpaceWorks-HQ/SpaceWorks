"""Deployment checks for Lane E activation-state integrity."""

from django.core.checks import Error, Tags, register

from .activation_integrity import inspect_activation_integrity


@register(Tags.database, deploy=True)
def check_b1_activation_integrity(app_configs, **kwargs):
    issues = inspect_activation_integrity()
    completeness = [item for item in issues if item.kind == "activation_count"]
    divergence = [item for item in issues if item.kind == "flag_state_divergence"]
    errors = []
    if completeness:
        details = ", ".join(
            f"{item.makerspace_id}({item.activation_count})"
            for item in completeness
        )
        errors.append(
            Error(
                "Retained makerspaces do not each have exactly one Lane E activation row: "
                f"{details}.",
                hint="Run `manage.py repair_b1_activation_state --dry-run`.",
                id="backup.E001",
            )
        )
    if divergence:
        details = ", ".join(
            f"{item.makerspace_id}(flag={'on' if item.flag_enabled else 'off'}, "
            f"state={item.activation_state})"
            for item in divergence
        )
        errors.append(
            Error(
                f"Lane E access flags and activation states diverge: {details}.",
                hint="Run `manage.py repair_b1_activation_state --dry-run`.",
                id="backup.E002",
            )
        )
    return errors
