"""Beat-less-safe kiosk lease cleanup (registered in `run_scheduled_tasks`)."""

from celery import shared_task


@shared_task(name="apps.makerspaces.tasks_station.purge_expired_operator_leases_task")
def purge_expired_operator_leases_task():
    from apps.makerspaces.station_lease_cleanup import purge_expired_operator_leases

    return purge_expired_operator_leases()
