from django.core.exceptions import ValidationError
from django.db import models

from apps.events.models_event import Event
from apps.makerspaces.models_stations import Station


class EventStationBinding(models.Model):
    """Event-owned relationship to shared, otherwise inert Station metadata."""

    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name="station_binding",
    )
    station = models.OneToOneField(
        Station,
        on_delete=models.CASCADE,
        related_name="event_binding",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.event_id and self.station_id:
            try:
                event_makerspace_id = self.event.makerspace_id
                station_makerspace_id = self.station.makerspace_id
                station_kind = self.station.kind
            except (Event.DoesNotExist, Station.DoesNotExist):
                # Field validation reports missing FK targets; avoid replacing that
                # useful error with a related-object lookup exception from clean().
                return
            if event_makerspace_id != station_makerspace_id:
                raise ValidationError("Event and Station must belong to the same makerspace.")
            if station_kind != Station.Kind.EVENT_CHECKIN:
                raise ValidationError("Event bindings require an event check-in Station.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
