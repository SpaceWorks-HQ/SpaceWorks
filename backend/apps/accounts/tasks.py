from celery import shared_task

from apps.accounts.services_challenge_purge import purge_spent_challenges


@shared_task(name="apps.accounts.tasks.purge_auth_challenges_task")
def purge_auth_challenges_task():
    return purge_spent_challenges()
