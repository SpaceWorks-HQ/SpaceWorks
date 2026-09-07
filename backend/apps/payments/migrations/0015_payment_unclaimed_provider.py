from django.db import migrations, models


# Extends the live guard from 0013 (which this REPLACES -- 0013's body is reproduced
# below, waived->paid_online exception included) with provider-claim enforcement.
#
# A charge raised while the space had no gateway configured is stamped `unclaimed`. The
# first checkout that reaches a provider claims it. That transition must be possible
# exactly once and never reversible, otherwise a settled charge could be re-pointed at a
# merchant account that never took the money -- the same reasoning that made provider
# provenance immutable in the first place.
FORWARD_SQL = """CREATE OR REPLACE FUNCTION payments_payment_terminal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'payment is immutable';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.provider <> 'unclaimed' AND NEW.provider <> OLD.provider THEN
    RAISE EXCEPTION 'payment provider is immutable once claimed';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.status <> 'pending' AND (NEW.status <> OLD.status OR NEW.amount <> OLD.amount) THEN
    IF current_setting('app.allow_waived_online_settlement', true) = 'on'
       AND OLD.status = 'waived' AND NEW.status = 'paid_online' AND NEW.amount = OLD.amount THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'terminal payment is immutable';
  END IF;
  RETURN COALESCE(NEW, OLD);
END; $$;"""

REVERSE_SQL = """CREATE OR REPLACE FUNCTION payments_payment_terminal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'payment is immutable';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.status <> 'pending' AND (NEW.status <> OLD.status OR NEW.amount <> OLD.amount) THEN
    IF current_setting('app.allow_waived_online_settlement', true) = 'on'
       AND OLD.status = 'waived' AND NEW.status = 'paid_online' AND NEW.amount = OLD.amount THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'terminal payment is immutable';
  END IF;
  RETURN COALESCE(NEW, OLD);
END; $$;"""


class Migration(migrations.Migration):
    # Chained off the ACTUAL leaf, read from the migrations directory -- not a number
    # quoted in a spec.
    dependencies = [("payments", "0014_refund_and_loan_settings")]

    operations = [
        # Choices-only: Django records the new member, the column is unchanged. Existing
        # rows keep their `stripe`/`razorpay` stamp and are therefore already claimed.
        migrations.AlterField(
            model_name="payment",
            name="provider",
            field=models.CharField(
                choices=[
                    ("stripe", "Stripe"),
                    ("razorpay", "Razorpay"),
                    ("unclaimed", "No online rail"),
                ],
                default="stripe",
                max_length=16,
            ),
        ),
        # Refund.provider reuses Payment.Provider.choices, so Django's state needs the
        # new member here too. It is unreachable in practice: a Refund is only ever raised
        # against a paid_online Payment, which is claimed by definition.
        migrations.AlterField(
            model_name="refund",
            name="provider",
            field=models.CharField(
                choices=[
                    ("stripe", "Stripe"),
                    ("razorpay", "Razorpay"),
                    ("unclaimed", "No online rail"),
                ],
                max_length=16,
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
