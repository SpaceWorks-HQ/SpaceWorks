"""Admission expiry and committed-settlement recovery for both schedulers."""

from celery import shared_task


@shared_task(name="apps.operations.tasks_admissions.sweep_membership_admissions_task")
def sweep_membership_admissions_task():
    from apps.makerspaces.membership_admission_payments import sweep_admissions

    return sweep_admissions()
