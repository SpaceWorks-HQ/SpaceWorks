from django.db import models


class EventCategory(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["makerspace", "slug"], name="event_category_space_slug")]
