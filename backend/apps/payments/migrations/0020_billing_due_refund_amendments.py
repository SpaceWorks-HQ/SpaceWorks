"""Preserve financial history while adding local billing policy and corrections."""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models
from apps.payments.models_billing import reminder_before_default, reminder_after_default


GUARD_SQL = """
CREATE OR REPLACE FUNCTION payments_manual_refund_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE charge payments_payment%ROWTYPE; previous payments_refund%ROWTYPE; counted numeric;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.provider <> 'manual' THEN RETURN OLD; END IF;
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'manual refunds are append-only';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.provider = 'manual' OR NEW.provider = 'manual' OR
       NEW.amends_id IS DISTINCT FROM OLD.amends_id THEN
      RAISE EXCEPTION 'manual refunds are append-only';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.provider <> 'manual' THEN
    IF NEW.amends_id IS NOT NULL THEN RAISE EXCEPTION 'only manual receipts can amend'; END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO charge FROM payments_payment WHERE id = NEW.payment_id FOR UPDATE;
  IF charge.status <> 'paid_offline' OR NEW.currency <> charge.currency THEN
    RAISE EXCEPTION 'manual refund must match an offline-settled charge';
  END IF;
  IF NEW.amends_id IS NOT NULL THEN
    SELECT * INTO previous FROM payments_refund WHERE id = NEW.amends_id;
    IF NOT FOUND OR previous.provider <> 'manual' OR previous.payment_id <> NEW.payment_id OR
       previous.amount <> NEW.amount OR previous.currency <> NEW.currency OR
       previous.id = NEW.id OR EXISTS(SELECT 1 FROM payments_refund WHERE amends_id = previous.id) THEN
      RAISE EXCEPTION 'correction must replace the same effective manual refund';
    END IF;
  END IF;
  SELECT COALESCE(SUM(r.amount), 0) INTO counted FROM payments_refund r
    WHERE r.payment_id = NEW.payment_id AND r.status IN ('pending', 'succeeded')
      AND (NEW.amends_id IS NULL OR r.id <> NEW.amends_id)
      AND NOT EXISTS(SELECT 1 FROM payments_refund child WHERE child.amends_id = r.id);
  IF counted + NEW.amount > charge.amount THEN
    RAISE EXCEPTION 'refunds exceed the payment amount';
  END IF;
  RETURN NEW;
END; $$;
CREATE FUNCTION payments_due_date_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.due_at IS DISTINCT FROM OLD.due_at THEN
    RAISE EXCEPTION 'charge due date is immutable';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER payments_due_date_guard BEFORE UPDATE ON payments_payment
FOR EACH ROW EXECUTE FUNCTION payments_due_date_guard();
"""


def restore_guard(apps, schema_editor):
    from importlib import import_module
    sql = import_module("apps.payments.migrations.0018_offline_refund_receipt").GUARD_SQL
    schema_editor.execute("DROP FUNCTION payments_due_date_guard() CASCADE;")
    schema_editor.execute("DROP FUNCTION payments_manual_refund_guard() CASCADE;")
    schema_editor.execute(sql, params=None)


def install_guard(apps, schema_editor):
    schema_editor.execute(GUARD_SQL, params=None)


class Migration(migrations.Migration):
    dependencies = [("payments", "0019_membership_request_subject")]

    operations = [
        migrations.AddField(model_name="payment", name="due_at", field=models.DateTimeField(null=True, blank=True)),
        migrations.AddIndex(model_name="payment", index=models.Index(
            fields=["makerspace", "status", "due_at"], name="payment_ms_status_due_idx",
        )),
        migrations.AddField(model_name="refund", name="amends", field=models.OneToOneField(
            to="payments.refund", null=True, blank=True, on_delete=django.db.models.deletion.CASCADE,
            related_name="amended_by",
        )),
        migrations.CreateModel(name="MakerspaceBillingSettings", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("makerspace", models.OneToOneField(to="makerspaces.makerspace", on_delete=django.db.models.deletion.CASCADE,
                                              related_name="billing_settings")),
            ("payment_terms_days", models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(365)])),
            ("reminder_days_before", models.JSONField(default=reminder_before_default, blank=True)),
            ("reminder_days_after", models.JSONField(default=reminder_after_default, blank=True)),
            ("max_reminders", models.PositiveSmallIntegerField(default=2, validators=[django.core.validators.MaxValueValidator(20)])),
        ]),
        migrations.RunPython(install_guard, restore_guard),
    ]
