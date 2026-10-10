"""Opt-in admissions; upgrade defaults preserve every legacy join/dues path."""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
from django.db.models import Q

from apps.forms_schema.validation import validate_form_schema


def backfill(apps, schema_editor):
    Space = apps.get_model("makerspaces", "Makerspace")
    Policy = apps.get_model("makerspaces", "MakerspaceMembershipSettings")
    PaymentSettings = apps.get_model("payments", "MakerspacePaymentSettings")
    db = schema_editor.connection.alias
    currencies = dict(PaymentSettings.objects.using(db).values_list("makerspace_id", "default_currency"))
    for space in Space.objects.using(db).iterator():
        Policy.objects.using(db).get_or_create(makerspace_id=space.pk, defaults={
            "configured": False,
            "join_mode": "approval" if space.membership_policy == "request" else space.membership_policy,
            "joining_fee": space.membership_dues_amount,
            "joining_fee_currency": currencies.get(space.pk, "usd"),
            "payment_timing": "after_activation", "rejoin_dues_rule": "once",
        })


SQL = """
CREATE FUNCTION membership_vouch_immutable() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('app.allow_immutable_delete', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'membership vouches are immutable';
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER membership_vouch_immutable_trigger BEFORE UPDATE OR DELETE
  ON makerspaces_membershipvouch FOR EACH ROW EXECUTE FUNCTION membership_vouch_immutable();
CREATE FUNCTION pii_fence_membership_application() RETURNS trigger AS $$
BEGIN
  PERFORM pii_assert_mapped_write_allowed(NEW.makerspace_id);
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER pii_fence_membership_application_trigger
  BEFORE INSERT OR UPDATE OF application_answers ON makerspaces_membershiprequest
  FOR EACH ROW EXECUTE FUNCTION pii_fence_membership_application();
"""
REVERSE_SQL = """
DROP TRIGGER IF EXISTS pii_fence_membership_application_trigger ON makerspaces_membershiprequest;
DROP FUNCTION IF EXISTS pii_fence_membership_application();
DROP TRIGGER IF EXISTS membership_vouch_immutable_trigger ON makerspaces_membershipvouch;
DROP FUNCTION IF EXISTS membership_vouch_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0079_staff_invitations_feature"),
        ("payments", "0019_membership_request_subject"),
        ("encryption", "0007_tenant_import_fence_operation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(name="MakerspaceMembershipSettings", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("configured", models.BooleanField(default=False)),
            ("join_mode", models.CharField(max_length=16, default="approval", choices=[("open", "Open"), ("approval", "Approval"), ("invite_only", "Invite only"), ("vouch", "Vouch"), ("closed", "Closed")])),
            ("vouches_required", models.PositiveSmallIntegerField(default=1)),
            ("voucher_min_tenure_days", models.PositiveIntegerField(default=30)),
            ("voucher_pending_limit", models.PositiveSmallIntegerField(default=3)),
            ("vouch_expiry_days", models.PositiveIntegerField(default=30)),
            ("vouch_replaces_approval", models.BooleanField(default=False)),
            ("payment_timing", models.CharField(max_length=24, default="after_activation", choices=[("after_activation", "Activate then charge"), ("before_activation", "Pay before activation")])),
            ("application_schema", models.JSONField(null=True, blank=True, default=None, validators=[validate_form_schema])),
            ("joining_fee", models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])),
            ("joining_fee_currency", models.CharField(max_length=3, default="usd")),
            ("rejoin_dues_rule", models.CharField(max_length=16, default="once", choices=[("once", "Joining dues once"), ("each_join", "Joining dues on each join")])),
            ("request_expiry_days", models.PositiveIntegerField(default=30)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("makerspace", models.OneToOneField(to="makerspaces.makerspace", on_delete=models.CASCADE, related_name="admission_settings")),
            ("default_plan", models.ForeignKey(to="makerspaces.membershipplan", null=True, blank=True, on_delete=models.SET_NULL, related_name="default_for_admissions")),
        ], options={"constraints": [
            models.CheckConstraint(condition=Q(joining_fee__gte=0), name="admission_fee_nonnegative"),
            models.CheckConstraint(condition=Q(vouches_required__gte=1, vouches_required__lte=5), name="admission_vouch_count_range"),
            models.CheckConstraint(condition=Q(voucher_pending_limit__gte=1), name="admission_voucher_limit_positive"),
            models.CheckConstraint(condition=Q(vouch_expiry_days__gte=1, request_expiry_days__gte=1), name="admission_expiry_positive"),
        ]}),
        migrations.AddField("membershiprequest", "admission_managed", models.BooleanField(default=False)),
        migrations.AddField("membershiprequest", "application_schema", models.JSONField(null=True, blank=True, default=None)),
        migrations.AddField("membershiprequest", "application_answers", models.TextField(null=True, blank=True, default=None)),
        migrations.AddField("membershiprequest", "selected_plan", models.ForeignKey(to="makerspaces.membershipplan", null=True, blank=True, on_delete=models.PROTECT)),
        migrations.AddField("membershiprequest", "admission_payment", models.ForeignKey(to="payments.payment", null=True, blank=True, on_delete=models.SET_NULL)),
        migrations.AddField("membershiprequest", "approved_at", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("membershiprequest", "approved_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_admissions")),
        migrations.AddField("membershiprequest", "expires_at", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("membershiprequest", "rejoining", models.BooleanField(default=False)),
        migrations.AddField("membershiprequest", "joining_fee", models.DecimalField(max_digits=12, decimal_places=2, default=0)),
        migrations.AddField("membershiprequest", "first_term_amount", models.DecimalField(max_digits=12, decimal_places=2, default=0)),
        migrations.AddField("membershiprequest", "charge_currency", models.CharField(max_length=3, default="usd")),
        migrations.AlterField("membershiprequest", "state", models.CharField(max_length=16, choices=[
            ("requested", "Requested"), ("invited", "Invited"), ("awaiting_vouches", "Awaiting vouches"),
            ("awaiting_payment", "Awaiting payment"), ("expired", "Expired"), ("canceled", "Canceled"),
            ("active", "Active"), ("revoked", "Revoked"),
        ])),
        migrations.RemoveConstraint("membershiprequest", "uniq_open_membership_request_user"),
        migrations.RemoveConstraint("membershiprequest", "uniq_open_membership_request_email"),
        migrations.AddConstraint("membershiprequest", models.UniqueConstraint(fields=["makerspace", "user"], condition=Q(state__in=["requested", "invited", "awaiting_vouches", "awaiting_payment"], user__isnull=False), name="uniq_open_membership_request_user")),
        migrations.AddConstraint("membershiprequest", models.UniqueConstraint(fields=["makerspace", "invite_email"], condition=Q(state__in=["requested", "invited", "awaiting_vouches", "awaiting_payment"]) & ~Q(invite_email=""), name="uniq_open_membership_request_email")),
        migrations.CreateModel(name="MembershipVouch", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("expires_at", models.DateTimeField()),
            ("makerspace", models.ForeignKey(to="makerspaces.makerspace", on_delete=models.CASCADE)),
            ("request", models.ForeignKey(to="makerspaces.membershiprequest", on_delete=models.CASCADE, related_name="vouches")),
            ("voucher", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="membership_vouches")),
        ], options={"ordering": ["created_at", "pk"], "constraints": [
            models.UniqueConstraint(fields=["request", "voucher"], name="uniq_membership_request_voucher"),
        ]}),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
