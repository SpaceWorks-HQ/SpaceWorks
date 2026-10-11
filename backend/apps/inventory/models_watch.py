"""One-shot member subscriptions; source delivery authority does not travel."""

from django.conf import settings
from django.db import models


class InventoryWatch(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    product = models.ForeignKey("inventory.InventoryProduct", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["product", "user"], name="inventory_watch_product_user_unique",
        )]
