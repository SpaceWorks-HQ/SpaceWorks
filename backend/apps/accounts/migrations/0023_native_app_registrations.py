import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def bind_existing_device_authority(apps, schema_editor):
    Challenge = apps.get_model("accounts", "DeviceAttestationChallenge")
    Grant = apps.get_model("accounts", "DeviceGrant")
    Registration = apps.get_model("accounts", "NativeAppRegistration")

    identities = set(
        Grant.objects.values_list("app_id", "platform", "environment")
    )
    identities.update(
        Challenge.objects.values_list("app_id", "platform", "environment")
    )
    for app_id, platform, environment in identities:
        registration, _ = Registration.objects.get_or_create(
            makerspace_id=None,
            app_id=app_id,
            platform=platform,
            environment=environment,
            defaults={
                "verifier_config_key": app_id,
                "status": "approved",
            },
        )
        Grant.objects.filter(
            registration_id__isnull=True,
            app_id=app_id,
            platform=platform,
            environment=environment,
        ).update(registration_id=registration.pk)
        Challenge.objects.filter(
            registration_id__isnull=True,
            app_id=app_id,
            platform=platform,
            environment=environment,
        ).update(registration_id=registration.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0022_user_self_registered_at"),
        ("makerspaces", "0064_makerspace_lifecycle_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="NativeAppRegistration",
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
                ("app_id", models.CharField(max_length=255)),
                (
                    "platform",
                    models.CharField(
                        choices=[("apple", "Apple"), ("android", "Android")],
                        max_length=16,
                    ),
                ),
                (
                    "environment",
                    models.CharField(
                        choices=[
                            ("development", "Development"),
                            ("production", "Production"),
                        ],
                        max_length=16,
                    ),
                ),
                ("verifier_config_key", models.CharField(max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("revoked", "Revoked"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_native_app_registrations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="native_app_registrations",
                        to="makerspaces.makerspace",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["platform", "app_id", "environment", "status"],
                        name="native_app_lookup_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("makerspace", "app_id", "platform", "environment"),
                        name="uniq_native_app_registration_scope",
                        nulls_distinct=False,
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="deviceattestationchallenge",
            name="registration",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="attestation_challenges",
                to="accounts.nativeappregistration",
            ),
        ),
        migrations.AddField(
            model_name="devicegrant",
            name="registration",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="device_grants",
                to="accounts.nativeappregistration",
            ),
        ),
        migrations.RunPython(
            bind_existing_device_authority,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="deviceattestationchallenge",
            name="registration",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="attestation_challenges",
                to="accounts.nativeappregistration",
            ),
        ),
        migrations.AlterField(
            model_name="devicegrant",
            name="registration",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="device_grants",
                to="accounts.nativeappregistration",
            ),
        ),
    ]
