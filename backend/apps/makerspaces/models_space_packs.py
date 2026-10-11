"""Deployment-global configuration profiles. Actor attribution lives in audit."""
from django.db import models

from .space_pack_format import open_pack


def validate_space_pack(value):
    from django.core.exceptions import ValidationError
    from rest_framework.exceptions import ValidationError as SerializerValidationError
    from .space_pack_validation import validate_configuration
    from .space_pack_format import PackError

    try:
        validate_configuration(open_pack(value))
    except (PackError, ValidationError, SerializerValidationError) as exc:
        raise ValidationError("Invalid configuration space pack.") from exc


class SpacePackProfile(models.Model):
    name = models.CharField(max_length=120, unique=True)
    pack = models.JSONField(validators=[validate_space_pack])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name
