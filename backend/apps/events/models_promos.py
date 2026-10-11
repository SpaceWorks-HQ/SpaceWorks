import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class EventPromoCode(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="promo_codes")
    code_digest = models.CharField(max_length=64, editable=False, default=secrets.token_hex)
    percent_off = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(100)])
    amount_off = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.event_id and self.event.makerspace_id != self.makerspace_id:
            raise ValidationError({"event": "Event must belong to this makerspace."})

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "code_digest"], name="event_promo_unique_code"),
            models.CheckConstraint(condition=Q(max_uses__gte=1), name="event_promo_positive_limit"),
            models.CheckConstraint(condition=Q(uses__lte=F("max_uses")), name="event_promo_usage_limit"),
            models.CheckConstraint(condition=Q(percent_off__lte=100, amount_off__gte=0), name="event_promo_valid_discount"),
            models.CheckConstraint(condition=(Q(percent_off__gt=0, amount_off=0) | Q(percent_off=0, amount_off__gt=0)), name="event_promo_one_discount"),
        ]
