"""Core receipt documents; numbering is transactional, documents append-only."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.payments.models_billing import default_account_codes, validate_account_codes


GUARD_SQL = """
CREATE FUNCTION payments_document_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE charge payments_payment%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_immutable_delete', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'payment documents are append-only';
  END IF;
  IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'payment documents are append-only'; END IF;
  IF num_nonnulls(NEW.settlement_id, NEW.refund_id, NEW.reverses_id) > 1 THEN
    RAISE EXCEPTION 'document must have only one financial source';
  END IF;
  IF jsonb_typeof(NEW.issuer) IS DISTINCT FROM 'object' OR
     jsonb_typeof(NEW.issuer->'name') IS DISTINCT FROM 'string' OR
     length(btrim(NEW.issuer->>'name')) = 0 THEN
    RAISE EXCEPTION 'invalid document issuer snapshot';
  END IF;
  SELECT * INTO charge FROM payments_payment WHERE id = NEW.payment_id;
  IF charge.makerspace_id <> NEW.makerspace_id OR charge.currency <> NEW.currency OR
     charge.status NOT IN ('paid_offline', 'paid_online') THEN
    RAISE EXCEPTION 'document must match a collected payment';
  END IF;
  IF NEW.settlement_id IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM payments_manualsettlement WHERE id = NEW.settlement_id AND payment_id = NEW.payment_id
      AND amount = NEW.amount AND currency = NEW.currency AND NEW.kind = 'receipt'
  ) THEN RAISE EXCEPTION 'document settlement belongs to another payment'; END IF;
  IF NEW.refund_id IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM payments_refund WHERE id = NEW.refund_id AND payment_id = NEW.payment_id AND status = 'succeeded'
      AND amount = NEW.amount AND currency = NEW.currency AND NEW.kind = 'credit_note'
  ) THEN RAISE EXCEPTION 'document refund is not succeeded on this payment'; END IF;
  IF NEW.reverses_id IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM payments_paymentdocument WHERE id = NEW.reverses_id AND payment_id = NEW.payment_id AND kind <> NEW.kind
      AND amount = NEW.amount
  ) THEN RAISE EXCEPTION 'document reversal must offset the same payment'; END IF;
  IF NEW.refund_id IS NULL AND NEW.reverses_id IS NULL AND
     (NEW.kind <> 'receipt' OR NEW.amount <> charge.amount OR
       (charge.status = 'paid_offline' AND NEW.settlement_id IS NULL)) THEN
    RAISE EXCEPTION 'receipt must match the full settlement';
  END IF;
  IF jsonb_typeof(NEW.lines) <> 'array' OR jsonb_array_length(NEW.lines) = 0 OR
     EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.lines) line WHERE
       jsonb_typeof(line->'label') IS DISTINCT FROM 'string' OR length(btrim(line->>'label')) = 0 OR
       line->>'quantity' IS NULL OR line->>'unit_amount' IS NULL OR line->>'total' IS NULL OR
       (line->>'quantity')::numeric <= 0 OR (line->>'unit_amount')::numeric < 0 OR
       (line->>'quantity')::numeric * (line->>'unit_amount')::numeric <> (line->>'total')::numeric) OR
     (SELECT SUM((line->>'total')::numeric) FROM jsonb_array_elements(NEW.lines) line) <> NEW.amount THEN
    RAISE EXCEPTION 'document lines must reconcile';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER payments_document_guard BEFORE INSERT OR UPDATE OR DELETE ON payments_paymentdocument
FOR EACH ROW EXECUTE FUNCTION payments_document_guard();
"""


def enable_documents(apps, schema_editor):
    Space = apps.get_model("makerspaces", "Makerspace")
    for space in Space.objects.using(schema_editor.connection.alias).all().iterator():
        features = list(space.enabled_features or [])
        if "billing.documents" not in features:
            Space.objects.using(schema_editor.connection.alias).filter(pk=space.pk).update(
                enabled_features=[*features, "billing.documents"])


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0020_billing_due_refund_amendments"),
        ("makerspaces", "0080_membership_admission"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField("makerspacebillingsettings", "number_prefix", models.CharField(max_length=32, blank=True, default="")),
        migrations.AddField("makerspacebillingsettings", "legal_name", models.CharField(max_length=150, blank=True, default="")),
        migrations.AddField("makerspacebillingsettings", "address", models.TextField(max_length=1000, blank=True, default="")),
        migrations.AddField("makerspacebillingsettings", "tax_id", models.CharField(max_length=64, blank=True, default="")),
        migrations.AddField("makerspacebillingsettings", "footer", models.TextField(max_length=1000, blank=True, default="")),
        migrations.AddField("makerspacebillingsettings", "account_codes", models.JSONField(
            default=default_account_codes, validators=[validate_account_codes], blank=True)),
        migrations.AddField("makerspacebillingsettings", "next_document_number", models.PositiveBigIntegerField(default=1)),
        migrations.AddConstraint("makerspacebillingsettings", models.CheckConstraint(
            condition=models.Q(next_document_number__gt=0), name="billing_document_counter_positive")),
        migrations.CreateModel("PaymentDocument", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("makerspace", models.ForeignKey(to="makerspaces.makerspace", on_delete=django.db.models.deletion.CASCADE)),
            ("payment", models.ForeignKey(to="payments.payment", on_delete=django.db.models.deletion.CASCADE, related_name="documents")),
            ("settlement", models.ForeignKey(to="payments.manualsettlement", on_delete=django.db.models.deletion.CASCADE, null=True, blank=True)),
            ("refund", models.ForeignKey(to="payments.refund", on_delete=django.db.models.deletion.CASCADE, null=True, blank=True)),
            ("reverses", models.OneToOneField(to="payments.paymentdocument", on_delete=django.db.models.deletion.CASCADE,
                                             null=True, blank=True, related_name="reversed_by")),
            ("sequence", models.PositiveBigIntegerField()), ("number", models.CharField(max_length=80)),
            ("kind", models.CharField(max_length=16, choices=[("receipt", "Receipt"), ("credit_note", "Credit note")])),
            ("issuer", models.JSONField(default=dict)), ("payer_label", models.CharField(max_length=150)),
            ("payer_type", models.CharField(max_length=16)), ("lines", models.JSONField(default=list)),
            ("amount", models.DecimalField(max_digits=12, decimal_places=2)), ("currency", models.CharField(max_length=3)),
            ("settlement_method", models.CharField(max_length=16)), ("settlement_reference", models.CharField(max_length=64, blank=True)),
            ("money_at", models.DateTimeField()), ("issued_at", models.DateTimeField(auto_now_add=True)),
            ("issued_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=django.db.models.deletion.PROTECT)),
            ("tax_breakdown", models.JSONField(null=True, blank=True, default=None)),
        ], options={"ordering": ["sequence"], "constraints": [
            models.UniqueConstraint(fields=["makerspace", "sequence"], name="document_space_sequence"),
            models.UniqueConstraint(fields=["makerspace", "number"], name="document_space_number"),
            models.UniqueConstraint(fields=["makerspace", "settlement"], condition=models.Q(settlement__isnull=False), name="document_settlement_once"),
            models.UniqueConstraint(fields=["makerspace", "refund"], condition=models.Q(refund__isnull=False), name="document_refund_once"),
            models.UniqueConstraint(fields=["makerspace", "payment"], condition=models.Q(
                settlement__isnull=True, refund__isnull=True, reverses__isnull=True, kind="receipt"), name="document_online_once"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="document_amount_positive"),
            models.CheckConstraint(condition=models.Q(sequence__gt=0), name="document_sequence_positive"),
            models.CheckConstraint(condition=models.Q(tax_breakdown__isnull=True), name="document_tax_unused"),
        ]}),
        migrations.RunSQL(GUARD_SQL, "DROP FUNCTION payments_document_guard() CASCADE;"),
        migrations.RunPython(enable_documents, migrations.RunPython.noop),
    ]
