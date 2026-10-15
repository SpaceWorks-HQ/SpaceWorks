"""Public-site settings, independent of the core hardware catalogue."""

from django.db import models


class PublicSiteSettings(models.Model):
    event_default_registration_audience = models.CharField(
        max_length=8, default="members",
        choices=[("members", "Members"), ("accounts", "Authenticated accounts"), ("invite", "Invited accounts")],
    )
    public_inventory_enabled = models.BooleanField(default=True)
    public_site_enabled = models.BooleanField(default=True)
    public_landing_page = models.CharField(
        max_length=16, default="auto",
        choices=[(key, key.title()) for key in
                 ("auto", "inventory", "events", "machines", "bookings", "membership")],
    )
    public_stats_enabled = models.BooleanField(default=False)
    public_stats_show_holder_names = models.BooleanField(default=False)

    class Meta:
        abstract = True
