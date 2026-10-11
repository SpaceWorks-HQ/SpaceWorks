from apps.accounts import rbac
from apps.makerspaces.platform import feature_enabled
from .models_materials import MachineMaterial


def catalogue(space, machine_type):
    if feature_enabled(space, "machines.material_catalogue"):
        rows = rbac.scope_verified_tenant(MachineMaterial.objects.all(), space).filter(machine_type=machine_type)
        if rows.exists():
            return list(rows.filter(is_active=True).order_by("name", "pk").values("id", "name", "colours"))
    config = machine_type.capability_config
    return [{"id": None, "name": name, "colours": config.get("accepted_colours", [])}
            for name in config.get("accepted_materials", [])]


def config_for(space, machine_type):
    rows = catalogue(space, machine_type)
    return {"accepted_materials": [row["name"] for row in rows],
            "accepted_colours": list(dict.fromkeys(c for row in rows for c in row["colours"]))}


def validate_selection(space, machine_type, material, colour):
    from django.core.exceptions import ValidationError
    rows = catalogue(space, machine_type)
    if not any(row["name"].casefold() == material.casefold() and
               colour.casefold() in {c.casefold() for c in row["colours"]} for row in rows):
        raise ValidationError("Material and colour are not accepted by this makerspace.")
