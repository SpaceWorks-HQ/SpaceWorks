from django.core.exceptions import ValidationError
from django.db import models

from apps.payments.models_settings import currency_validator


class Payment(models.Model):
    class SubjectType(models.TextChoices):
        MACHINE_SERVICE_REQUEST = "machine_service_request", "Machine service request"
        BOOKING = "booking", "Booking"
        EVENT_REGISTRATION = "event_registration", "Event registration"
        MAKERSPACE_MEMBERSHIP = "makerspace_membership", "Makerspace membership"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID_ONLINE = "paid_online", "Paid online"
        PAID_OFFLINE = "paid_offline", "Paid offline"
        WAIVED = "waived", "Waived"
        CANCELED = "canceled", "Canceled"

    class StripeProvider(models.TextChoices):
        RAW = "raw", "Makerspace raw credentials"
        CONNECT = "connect", "Stripe Connect"

    class Provider(models.TextChoices):
        """Which vendor holds this charge.

        Distinct from `stripe_provider`, which says how STRIPE credentials were
        resolved (raw vs Connect) and is meaningless for any other vendor.
        """

        STRIPE = "stripe", "Stripe"
        RAZORPAY = "razorpay", "Razorpay"

    class OnlineRail(models.TextChoices):
        CHECKOUT = 'checkout', 'Stripe Checkout'
        NATIVE_PAYMENT_INTENT = 'native_payment_intent', 'Native payment intent'

    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.PROTECT, related_name="payments")
    subject_type = models.CharField(max_length=48, choices=SubjectType.choices)
    subject_id = models.PositiveBigIntegerField()
    member = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    # Which makerspace's member area may surface this charge, beyond the owning space.
    # A collaborative event is hosted by A, so the Payment is A's (ownership decides which
    # Stripe account is charged), but the member reached it through B and has no membership
    # at A. This column is deliberately NOT on EventRegistration: a purge clears that row's
    # provenance (activity history is what a purge is for) and the host's own purge deletes
    # the registration outright, either of which would strand a receipt or a payable debt.
    # SET_NULL, not PROTECT: this is a routing hint, not ownership -- `makerspace` is that.
    via_makerspace = models.ForeignKey(
        "makerspaces.Makerspace", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payments_via",
    )
    # Snapshotted at creation so a receipt stays readable after its subject row is purged.
    # Same idiom as `destination_label` on notification delivery logs. Financial metadata,
    # so it must never carry PII -- callers pass an event title, a space name or a service
    # title, never a person's name, contact details or custom-form answers.
    subject_label = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # Provider-agnostic columns (phase 4). The `stripe_*` columns below are retained as
    # read-only historic, exactly as `MachineServiceRequest.payment_*` was when Payment
    # took over: rows are immutable once terminal, so a migration may only ADD nullable
    # columns and may never rewrite what is already there.
    provider = models.CharField(
        max_length=16, choices=Provider.choices, default=Provider.STRIPE
    )
    external_order_id = models.CharField(max_length=255, null=True, blank=True)
    external_payment_id = models.CharField(max_length=255, null=True, blank=True)
    checkout_url = models.URLField(blank=True, default="")
    stripe_provider = models.CharField(max_length=16, choices=StripeProvider.choices, default=StripeProvider.RAW)
    stripe_connected_account_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_application_fee_amount = models.PositiveBigIntegerField(default=0)
    online_rail = models.CharField(
        max_length=32,
        choices=OnlineRail.choices,
        null=True,
        blank=True,
    )
    stripe_checkout_session_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_checkout_url = models.URLField(blank=True, default="")
    stripe_checkout_session_expired_at = models.DateTimeField(null=True, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="created_payments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["via_makerspace", "member"],
                name="payment_via_makerspace_member_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=["makerspace", "subject_type", "subject_id"], name="payment_one_per_subject"),
            # Scoped BY PROVIDER: two vendors are free to mint the same opaque id, and a
            # global unique index would make the second one unstorable. Partial, because
            # NULL means "no checkout raised yet" and many rows sit in that state.
            models.UniqueConstraint(
                fields=["provider", "external_order_id"],
                name="payment_external_order_once_per_provider",
                condition=models.Q(external_order_id__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["provider", "external_payment_id"],
                name="payment_external_payment_once_per_provider",
                condition=models.Q(external_payment_id__isnull=False),
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
        ]
        ordering = ["-created_at"]

    def _subject_identity_unchanged(self):
        """True when this is a saved row still pointing at the same subject and member.

        A missing subject is legitimate for a payment whose subject was purged, but only if
        nothing about who owes what has been edited. Skipping validation merely because `pk`
        exists would be too broad -- it would let an existing row be repointed at a foreign
        subject. New rows always validate.
        """
        if self._state.adding or not self.pk:
            return False
        return (
            type(self)
            .objects.filter(
                pk=self.pk,
                makerspace_id=self.makerspace_id,
                subject_type=self.subject_type,
                subject_id=self.subject_id,
                member_id=self.member_id,
            )
            .exists()
        )

    def clean(self):
        self.currency = (self.currency or "").lower()
        currency_validator(self.currency)
        subject_identity_unchanged = self._subject_identity_unchanged()
        if self.subject_type == self.SubjectType.MACHINE_SERVICE_REQUEST and self.subject_id:
            from apps.machines.models import MachineServiceRequest

            if not subject_identity_unchanged and not MachineServiceRequest.objects.filter(
                pk=self.subject_id,
                makerspace_id=self.makerspace_id,
            ).exists():
                raise ValidationError({"subject_id": "Payment subject must belong to the payment makerspace."})
        if self.subject_type == self.SubjectType.BOOKING and self.subject_id:
            from apps.bookings.models import Booking

            if not subject_identity_unchanged:
                booking_exists = Booking.objects.filter(
                    pk=self.subject_id,
                    space__makerspace_id=self.makerspace_id,
                ).exists()
                if not booking_exists:
                    raise ValidationError(
                        {"subject_id": "Payment subject must belong to the payment makerspace."}
                    )
        if self.subject_type == self.SubjectType.EVENT_REGISTRATION and self.subject_id:
            from apps.events.models import EventRegistration

            if not subject_identity_unchanged:
                registration_exists = EventRegistration.objects.filter(
                    pk=self.subject_id,
                    event__makerspace_id=self.makerspace_id,
                ).exists()
                if not registration_exists:
                    raise ValidationError(
                        {"subject_id": "Payment subject must belong to the payment makerspace."}
                    )
        if self.subject_type == self.SubjectType.MAKERSPACE_MEMBERSHIP and self.subject_id:
            from apps.makerspaces.models import MakerspaceMembership

            membership = MakerspaceMembership.objects.filter(
                pk=self.subject_id,
                makerspace_id=self.makerspace_id,
            ).only("user_id").first()
            if membership is None and not subject_identity_unchanged:
                raise ValidationError(
                    {"subject_id": "Payment subject must belong to the payment makerspace."}
                )
            if membership is not None and self.member_id != membership.user_id:
                raise ValidationError(
                    {"member": "Payment member must be the membership user."}
                )

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values(
                "status", "amount", "provider", "stripe_provider", "stripe_connected_account_id", "stripe_application_fee_amount", "online_rail"
            ).first()
            if original and original["status"] != self.Status.PENDING and (
                original["status"] != self.status or original["amount"] != self.amount
            ):
                raise ValidationError("Terminal payments are immutable.")
            if original and any(
                original[field] != getattr(self, field)
                for field in ("provider", "stripe_provider", "stripe_connected_account_id", "stripe_application_fee_amount")
            ):
                # `provider` joins the provenance set: moving a charge between vendors
                # would point the row at a merchant account that never took the money,
                # and every settlement and refund path after it would be wrong.
                raise ValidationError("Payment provenance is immutable.")
            if (
                original
                and original['online_rail'] is not None
                and original['online_rail'] != self.online_rail
            ):
                raise ValidationError('The online payment rail is immutable once claimed.')
        self.full_clean()
        return super().save(*args, **kwargs)


class ProcessedStripeEvent(models.Model):
    """Webhook idempotency, for every provider.

    Kept under its original name and table: renaming a model whose rows are the only
    defence against double-settling a real charge is a migration risk with no payoff.
    The `provider` column is what generalises it -- two vendors can emit the same event
    id, and without it the second one would be silently swallowed as a duplicate.
    """

    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.PROTECT, related_name="processed_stripe_events")
    provider = models.CharField(max_length=16, default=Payment.Provider.STRIPE)
    stripe_event_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "provider", "stripe_event_id"],
                name="webhook_event_once_per_makerspace_provider",
            )
        ]
