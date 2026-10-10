import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0025_user_is_tenant_dump_stub"),
        ("makerspaces", "0076_station_operator_leases"),
    ]
    operations = [
        migrations.CreateModel(name="UserMFA", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("secret", models.TextField(blank=True)),
            ("enabled_at", models.DateTimeField(null=True)),
            ("last_step", models.BigIntegerField(default=-1)),
            ("recovery_digests", models.JSONField(default=list)),
            ("version", models.UUIDField(default=uuid.uuid4)),
            ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="MFAChallenge", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("token_digest", models.CharField(max_length=64, unique=True)),
            ("credential_fingerprint", models.CharField(max_length=64)),
            ("auth_generation", models.CharField(max_length=64)),
            ("mfa_version", models.UUIDField()),
            ("context", models.JSONField(default=dict)),
            ("pending_secret", models.TextField(blank=True)),
            ("expires_at", models.DateTimeField()),
            ("consumed_at", models.DateTimeField(null=True)),
            ("attempts", models.PositiveSmallIntegerField(default=0)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="StaffInvitation", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("email_ciphertext", models.TextField()),
            ("granted_actions", models.JSONField(default=list)),
            ("token_digest", models.CharField(max_length=64, unique=True)),
            ("expires_at", models.DateTimeField()),
            ("accepted_at", models.DateTimeField(null=True)),
            ("revoked_at", models.DateTimeField(null=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
            ("accepted_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="staff_invitations_accepted", to=settings.AUTH_USER_MODEL)),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="staff_invitations_created", to=settings.AUTH_USER_MODEL)),
            ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ("role", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspacerole")),
        ]),
    ]
