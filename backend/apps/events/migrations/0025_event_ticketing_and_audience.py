import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("events", "0024_event_cancellation_policy")]

    operations = [
        migrations.CreateModel(
            name="EventCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(max_length=100)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ],
            options={"ordering": ["name", "id"], "constraints": [models.UniqueConstraint(fields=("makerspace", "slug"), name="event_category_space_slug")]},
        ),
        migrations.CreateModel(
            name="EventInvite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_digest", models.CharField(default=secrets.token_hex, editable=False, max_length=64)),
                ("email_digest", models.CharField(blank=True, default="", editable=False, max_length=64)),
                ("max_uses", models.PositiveIntegerField(default=1)),
                ("uses", models.PositiveIntegerField(default=0)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invites", to="events.event")),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("event", "code_digest"), name="event_invite_unique_code"),
                models.CheckConstraint(condition=models.Q(max_uses__gte=1), name="event_invite_positive_limit"),
                models.CheckConstraint(condition=models.Q(uses__lte=models.F("max_uses")), name="event_invite_usage_limit"),
            ]},
        ),
        migrations.CreateModel(
            name="EventPromoCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_digest", models.CharField(default=secrets.token_hex, editable=False, max_length=64)),
                ("percent_off", models.PositiveIntegerField(default=0, validators=[MaxValueValidator(100)])),
                ("amount_off", models.DecimalField(decimal_places=2, default=0, max_digits=12, validators=[MinValueValidator(0)])),
                ("max_uses", models.PositiveIntegerField(default=1)),
                ("uses", models.PositiveIntegerField(default=0)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="promo_codes", to="events.event")),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("event", "code_digest"), name="event_promo_unique_code"),
                models.CheckConstraint(condition=models.Q(max_uses__gte=1), name="event_promo_positive_limit"),
                models.CheckConstraint(condition=models.Q(uses__lte=models.F("max_uses")), name="event_promo_usage_limit"),
                models.CheckConstraint(condition=models.Q(percent_off__lte=100, amount_off__gte=0), name="event_promo_valid_discount"),
                models.CheckConstraint(condition=(models.Q(percent_off__gt=0, amount_off=0) | models.Q(percent_off=0, amount_off__gt=0)), name="event_promo_one_discount"),
            ]},
        ),
        migrations.CreateModel(
            name="EventTicketType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=12, validators=[MinValueValidator(0)])),
                ("audience", models.CharField(choices=[("member", "Active members"), ("public", "All accounts")], default="public", max_length=8)),
                ("capacity", models.PositiveIntegerField(default=0)),
                ("sales_start_at", models.DateTimeField(blank=True, null=True)),
                ("sales_end_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="ticket_types", to="events.event")),
                ("series", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="ticket_types", to="events.eventseries")),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="makerspaces.makerspace")),
            ],
            options={"ordering": ["id"], "constraints": [
                models.CheckConstraint(condition=models.Q(amount__gte=0), name="event_ticket_nonnegative"),
                models.CheckConstraint(condition=(models.Q(event__isnull=False, series__isnull=True) | models.Q(event__isnull=True, series__isnull=False)), name="event_ticket_one_owner"),
                models.CheckConstraint(condition=(models.Q(sales_start_at__isnull=True) | models.Q(sales_end_at__isnull=True) | models.Q(sales_end_at__gt=models.F("sales_start_at"))), name="event_ticket_sales_window"),
            ]},
        ),
        migrations.AddField(model_name="event", name="registration_audience", field=models.CharField(choices=[("members", "Members"), ("accounts", "Authenticated accounts"), ("invite", "Invited accounts")], default="members", max_length=8)),
        migrations.AddField(model_name="eventseries", name="registration_audience", field=models.CharField(choices=[("members", "Members"), ("accounts", "Authenticated accounts"), ("invite", "Invited accounts")], default="members", max_length=8)),
        migrations.AddField(model_name="event", name="category", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="events.eventcategory")),
        migrations.AddField(model_name="event", name="tags", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="eventregistration", name="registration_audience", field=models.CharField(choices=[("members", "Members"), ("accounts", "Authenticated accounts"), ("invite", "Invited accounts")], default="members", max_length=8)),
        migrations.AddField(model_name="eventregistration", name="ticket_type", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="events.eventtickettype")),
        migrations.AddField(model_name="eventregistration", name="invite", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="events.eventinvite")),
        migrations.AddField(model_name="eventregistration", name="promo_code", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="events.eventpromocode")),
        migrations.AddField(model_name="eventregistration", name="quoted_amount", field=models.DecimalField(blank=True, null=True, decimal_places=2, max_digits=12)),
        migrations.AddField(model_name="eventregistration", name="discount_amount", field=models.DecimalField(decimal_places=2, default=0, max_digits=12)),
    ]
