from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.backup.models import B1ActivationState
from apps.makerspaces.models import Makerspace


@receiver(post_save, sender=Makerspace, dispatch_uid="backup.create_b1_activation_state")
def create_b1_activation_state(sender, instance, created, **kwargs):
    if not created:
        return
    B1ActivationState.objects.get_or_create(
        makerspace=instance,
        defaults={
            "state": (
                B1ActivationState.State.ON
                if instance.superadmin_access_enabled
                else B1ActivationState.State.OFF_PENDING
            )
        },
    )
