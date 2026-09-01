from django.core.exceptions import ObjectDoesNotExist

from .types import Fidelity


def portable_projected_rows(dataset, page):
    if dataset.fidelity is not Fidelity.PORTABLE:
        return page, page
    from apps.tenant_migration.admission import export_row_policy

    emitted, contributors = [], []
    for row in page:
        emit, contributes = export_row_policy(dataset.model, row)
        if emit:
            emitted.append(row)
        if emit and contributes:
            contributors.append(row)
    return emitted, contributors


def portable_approval(job):
    direct = getattr(job, "disclosure_approval", None)
    if direct is not None:
        return direct
    try:
        return job.migration_export.disclosure_approval
    except (AttributeError, ObjectDoesNotExist):
        from apps.tenant_migration.protocol_errors import ClosureAdmissionError

        raise ClosureAdmissionError(
            "PORTABLE export requires an exact source-superadmin disclosure approval."
        )
