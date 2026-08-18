from django.db import migrations


FORWARD_SQL = """CREATE OR REPLACE FUNCTION payments_payment_terminal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

REVERSE_SQL = """CREATE OR REPLACE FUNCTION payments_payment_terminal_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'payment is immutable';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.status <> 'pending' AND (NEW.status <> OLD.status OR NEW.amount <> OLD.amount) THEN
    RAISE EXCEPTION 'terminal payment is immutable';
  END IF;
  RETURN COALESCE(NEW, OLD);
END; $$;"""


class Migration(migrations.Migration):
    dependencies = [("payments", "0012_payment_subject_label")]

    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
