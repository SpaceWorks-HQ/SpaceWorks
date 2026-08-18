import uuid

import django.db.models.deletion
import django.db.models.lookups
import django.utils.timezone
from django.db import migrations, models


def _provision_existing_scopes(apps, schema_editor):
    """Give the global scope and every existing makerspace a key at migrate time.

    Without this, an upgraded deployment that sets AUDIT_MAC_MASTER_KEY would have the
    key configured but no key ROW for any pre-existing scope, so every audited mutation
    would log audit_mac_key_unavailable and store unattested rows until someone ran the
    provision command. Skipped when attestation is not configured -- that deployment has
    deliberately not switched it on yet.
    """
    import secrets

    from apps.audit.keys import (
        _cutover_mac,
        _scope_id,
        _wrap_key,
        audit_mac_configured,
    )

    if not audit_mac_configured():
        return
    AuditMacKey = apps.get_model("audit", "AuditMacKey")
    AuditLog = apps.get_model("audit", "AuditLog")
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    scope_ids = [None, *Makerspace.objects.values_list("pk", flat=True)]
    for makerspace_id in scope_ids:
        if AuditMacKey.objects.filter(makerspace_id=makerspace_id).exists():
            continue
        # Everything this scope already has predates attestation. Leaving the default 0
        # would report every existing row as MAC_MISSING the first time an operator
        # verified an upgraded deployment.
        cutover = (
            AuditLog.objects.filter(makerspace_id=makerspace_id)
            .order_by("-pk")
            .values_list("pk", flat=True)
            .first()
            or 0
        )
        key = secrets.token_bytes(32)
        AuditMacKey.objects.create(
            makerspace_id=makerspace_id,
            wrapped_key=_wrap_key(_scope_id(makerspace_id), key),
            attested_from_id=cutover,
            attested_from_mac=_cutover_mac(key, _scope_id(makerspace_id), cutover),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0003_auditlog_purge_delete_guard"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditMacKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("wrapped_key", models.BinaryField()),
                ("attested_from_id", models.BigIntegerField(default=0)),
                ("attested_from_mac", models.BinaryField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "makerspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audit_mac_keys",
                        to="makerspaces.makerspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("makerspace",),
                        name="uniq_audit_mac_key_scope",
                        nulls_distinct=False,
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="auditlog",
            name="event_uuid",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="event_uuid",
            field=models.UUIDField(
                blank=True,
                default=uuid.uuid4,
                editable=False,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="row_mac",
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="created_at",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
            ),
        ),
        migrations.AddConstraint(
            model_name="auditlog",
            constraint=models.CheckConstraint(
                condition=django.db.models.lookups.Exact(
                    models.Func(
                        models.F("row_mac"),
                        function="OCTET_LENGTH",
                        output_field=models.IntegerField(),
                    ),
                    32,
                ),
                name="ck_audit_log_row_mac_32_bytes",
            ),
        ),
        migrations.RunPython(
            _provision_existing_scopes, migrations.RunPython.noop, elidable=False
        ),
    ]
