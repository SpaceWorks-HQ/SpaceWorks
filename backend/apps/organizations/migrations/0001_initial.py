import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("makerspaces", "0064_makerspace_lifecycle_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organization",
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
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(unique=True)),
                ("legal_name", models.CharField(blank=True, max_length=200)),
                ("registration_number", models.CharField(blank=True, max_length=100)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("billing_email", models.EmailField(blank=True, max_length=254)),
                ("logo_key", models.CharField(blank=True, max_length=300)),
                ("website", models.URLField(blank=True)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_organizations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("name", "id")},
        ),
        migrations.CreateModel(
            name="OrganizationMakerspace",
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
                (
                    "relationship",
                    models.CharField(
                        choices=[
                            ("owner", "Owner"),
                            ("manager", "Manager"),
                            ("affiliate", "Affiliate"),
                        ],
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_organization_makerspace_links",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="organization_links",
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="makerspace_links",
                        to="organizations.organization",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="organization",
            name="makerspaces",
            field=models.ManyToManyField(
                blank=True,
                related_name="organizations",
                through="organizations.OrganizationMakerspace",
                to="makerspaces.makerspace",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationmakerspace",
            constraint=models.UniqueConstraint(
                fields=("organization", "makerspace"),
                name="uniq_organization_makerspace_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationmakerspace",
            constraint=models.UniqueConstraint(
                condition=models.Q(("relationship", "owner")),
                fields=("makerspace",),
                name="uniq_owner_per_makerspace",
            ),
        ),
    ]

