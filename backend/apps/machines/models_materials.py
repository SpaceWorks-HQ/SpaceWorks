from django.db import models
from django.db.models.functions import Lower
from django.core.exceptions import ValidationError


def validate_colours(value):
    if (not isinstance(value, list) or not value or len(value) > 100
            or any(not isinstance(name, str) or not name.strip() or len(name) > 100 for name in value)
            or len({name.casefold() for name in value}) != len(value)):
        raise ValidationError("Colours must be a nonempty list of unique names (up to 100).")


class MachineMaterial(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    machine_type = models.ForeignKey("machines.MachineType", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    colours = models.JSONField(default=list, validators=[validate_colours])
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(Lower("name"), "makerspace", "machine_type",
                                                name="machine_material_tenant_type_name_unique")]

    def clean(self):
        if self.machine_type.makerspace_id not in (None, self.makerspace_id):
            raise ValidationError("Machine type belongs to another makerspace.")
