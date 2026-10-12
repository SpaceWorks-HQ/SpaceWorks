from django.db import models
from django.core.validators import MinValueValidator


class StocktakePolicy(models.Model):
    makerspace = models.OneToOneField("makerspaces.Makerspace", on_delete=models.CASCADE)
    blind_default = models.BooleanField(default=False)
    # Null preserves mandatory approval for every session; absolute units per line.
    variance_threshold = models.PositiveIntegerField(null=True, blank=True)


class StocktakeSchedule(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    container = models.ForeignKey("boxes.Box", null=True, blank=True, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    interval_days = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    next_due = models.DateField()
    blind = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(interval_days__gt=0),
                                              name="stocktake_schedule_interval_positive")]
