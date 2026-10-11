from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
from django.db.models.functions import Lower
import apps.machines.intake
import apps.machines.models_materials
import apps.machines.public_detail_validation


def seed_catalogue(apps, schema_editor):
    space = apps.get_model("makerspaces", "Makerspace")
    machine_type = apps.get_model("machines", "MachineType").objects.filter(
        makerspace__isnull=True, slug="3d_printer").first()
    if machine_type is None:
        return
    material = apps.get_model("machines", "MachineMaterial")
    config = machine_type.capability_config
    for pk in space.objects.values_list("pk", flat=True).iterator():
        material.objects.bulk_create([material(makerspace_id=pk, machine_type_id=machine_type.pk,
            name=name, colours=config["accepted_colours"])
            for name in config["accepted_materials"]])


STATUS_TRIGGER = """
UPDATE machines_machine SET status_since = updated_at;
CREATE FUNCTION machine_status_since_wp4() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN NEW.status_since := clock_timestamp();
  ELSE NEW.status_since := OLD.status_since;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER machine_status_since_wp4 BEFORE UPDATE ON machines_machine
FOR EACH ROW EXECUTE FUNCTION machine_status_since_wp4();
"""


class Migration(migrations.Migration):
    dependencies = [("machines", "0025_machine_type_policy")]
    operations = [
        migrations.AddField(model_name="machine", name="status_since", field=models.DateTimeField(default=django.utils.timezone.now, editable=False)),
        migrations.AddField(model_name="machine", name="public_fields", field=models.JSONField(blank=True, default=list, validators=[apps.machines.public_detail_validation.validate_public_fields])),
        migrations.AddField(model_name="machinetype", name="intake_schema", field=models.JSONField(blank=True, default=dict, validators=[apps.machines.intake.validate_intake_schema])),
        migrations.CreateModel(name="MachineMaterial", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=100)),
            ("colours", models.JSONField(default=list, validators=[apps.machines.models_materials.validate_colours])),
            ("is_active", models.BooleanField(default=True)),
            ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ("machine_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="machines.machinetype")),
        ], options={"constraints": [models.UniqueConstraint(Lower("name"), "makerspace", "machine_type", name="machine_material_tenant_type_name_unique")]}),
        migrations.RunPython(seed_catalogue, migrations.RunPython.noop),
        migrations.RunSQL(STATUS_TRIGGER, "DROP TRIGGER machine_status_since_wp4 ON machines_machine; DROP FUNCTION machine_status_since_wp4();"),
    ]
