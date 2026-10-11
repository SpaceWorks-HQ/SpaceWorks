"""Ticket templates belong to a series; sellable copies belong to occurrences."""

from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class EventTicketType(models.Model):
    class Audience(models.TextChoices):
        MEMBER = "member", "Active members"
        PUBLIC = "public", "All accounts"

    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.CASCADE, related_name="ticket_types")
    series = models.ForeignKey("events.EventSeries", null=True, blank=True, on_delete=models.CASCADE, related_name="ticket_types")
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.PUBLIC)
    capacity = models.PositiveIntegerField(default=0)
    sales_start_at = models.DateTimeField(null=True, blank=True)
    sales_end_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if bool(self.event_id) == bool(self.series_id):
            raise ValidationError("Choose exactly one event or series owner.")
        for field in ("event", "series"):
            owner = getattr(self, field)
            if owner and owner.makerspace_id != self.makerspace_id:
                raise ValidationError({field: "Owner must belong to this makerspace."})

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="event_ticket_nonnegative"),
            models.CheckConstraint(condition=(Q(event__isnull=False, series__isnull=True) | Q(event__isnull=True, series__isnull=False)), name="event_ticket_one_owner"),
            models.CheckConstraint(condition=(Q(sales_start_at__isnull=True) | Q(sales_end_at__isnull=True) | Q(sales_end_at__gt=F("sales_start_at"))), name="event_ticket_sales_window"),
        ]
