from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_organizationmembership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="public_profile_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="organizationmembership",
            name="governance_actions",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name="OrganizationInvitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_digest", models.CharField(editable=False, max_length=64, unique=True)),
                ("granted_actions", models.JSONField(blank=True, default=list)),
                ("governance_actions", models.JSONField(blank=True, default=list)),
                ("expires_at", models.DateTimeField()),
                ("redeemed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_organization_invitations", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invitations", to="organizations.organization")),
                ("redeemed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="redeemed_organization_invitations", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [models.Index(condition=models.Q(("redeemed_at__isnull", True), ("revoked_at__isnull", True)), fields=["organization", "expires_at"], name="org_invitation_active_idx")],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(models.Q(("redeemed_at__isnull", True), ("redeemed_by__isnull", True)), models.Q(("redeemed_at__isnull", False), ("redeemed_by__isnull", False)), _connector="OR"), name="org_invitation_redemption_complete"),
                    models.CheckConstraint(condition=models.Q(("redeemed_at__isnull", True), ("revoked_at__isnull", True), _connector="OR"), name="org_invitation_not_redeemed_revoked"),
                ],
            },
        ),
    ]
