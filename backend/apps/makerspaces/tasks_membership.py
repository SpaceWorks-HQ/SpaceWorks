"""Beat-less-safe membership renewal sweep (registered in `run_scheduled_tasks`)."""

from celery import shared_task


@shared_task(name="apps.makerspaces.tasks_membership.run_membership_renewals_task")
def run_membership_renewals_task():
    from apps.makerspaces.membership_plan_services import run_membership_renewals

    return run_membership_renewals()
