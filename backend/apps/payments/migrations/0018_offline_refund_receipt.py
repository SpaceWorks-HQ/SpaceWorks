"""Manual refunds share the refund balance and retain an immutable cash-book receipt."""

from django.db import migrations, models


METHODS = [
    ("cash", "Cash"), ("upi", "UPI"), ("bank_transfer", "Bank transfer"),
    ("card_machine", "Card machine"), ("cheque", "Cheque"), ("other", "Other"),
]

# The insert lock covers bypasses of the service too; append-only is enforced against
# QuerySet.update/delete and raw SQL, just like ManualSettlement. Online refunds keep
# their existing pending -> terminal webhook lifecycle.
GUARD_SQL = """
CREATE FUNCTION payments_manual_refund_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE charge payments_payment%ROWTYPE; counted numeric;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.provider <> 'manual' THEN RETURN OLD; END IF;
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'manual refunds are append-only';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.provider = 'manual' OR NEW.provider = 'manual' THEN
      RAISE EXCEPTION 'manual refunds are append-only';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.provider <> 'manual' THEN RETURN NEW; END IF;
  SELECT * INTO charge FROM payments_payment WHERE id = NEW.payment_id FOR UPDATE;
  IF charge.status <> 'paid_offline' OR NEW.currency <> charge.currency THEN
    RAISE EXCEPTION 'manual refund must match an offline-settled charge';
  END IF;
  SELECT COALESCE(SUM(amount), 0) INTO counted FROM payments_refund
    WHERE payment_id = NEW.payment_id AND status IN ('pending', 'succeeded');
  IF counted + NEW.amount > charge.amount THEN
    RAISE EXCEPTION 'refunds exceed the payment amount';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER payments_manual_refund_guard BEFORE INSERT OR UPDATE OR DELETE
ON payments_refund FOR EACH ROW EXECUTE FUNCTION payments_manual_refund_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("payments", "0017_settlement_cascade")]

    operations = [
        migrations.AlterField(
            model_name="refund", name="provider",
            field=models.CharField(max_length=16, choices=[
                ("stripe", "Stripe"), ("razorpay", "Razorpay"), ("manual", "Manual"),
            ]),
        ),
        migrations.AddField(
            model_name="refund", name="method",
            field=models.CharField(max_length=16, choices=METHODS, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="refund", name="reference",
            field=models.CharField(max_length=64, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="refund", name="refunded_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name="refund",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(provider="manual", status="succeeded", refunded_at__isnull=False,
                             settled_at__isnull=False, external_refund_id__isnull=True,
                             method__in=[value for value, _ in METHODS])
                    | (~models.Q(provider="manual") & models.Q(method="", reference="", refunded_at__isnull=True))
                ),
                name="refund_manual_receipt_required",
            ),
        ),
        migrations.RunSQL(GUARD_SQL, "DROP FUNCTION payments_manual_refund_guard() CASCADE;"),
    ]
