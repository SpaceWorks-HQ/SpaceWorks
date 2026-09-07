"""Membership plans and the dated terms a membership holds under them.

Forward plan phase 6 ("Membership plans and renewals"). Plans are OPTIONAL: a membership
with no term at all is a perfectly good membership, exactly as before this file existed.
A term is created when a join request is approved with a plan, or by staff. The renewal
task (`membership_plan_services.run_membership_renewals`) raises ONE charge inside the
renewal window when `payments.membership` is effectively on, and flips terms past
`ends_at` to `expired`; with the feature off the term simply expires and staff renew by
hand, dues out of band.

Expiry never touches `MakerspaceMembership.status` or `User.access_status`. The only
effect an expired term can have is the per-makerspace opt-in
`Makerspace.lapsed_members_cannot_borrow`, enforced by `request_access.require_current_term`
through the existing who-may-submit rule -- no new access state.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class MembershipPlan(models.Model):
    class Interval(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"
        CUSTOM_DAYS = "custom_days", "Custom number of days"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="membership_plans"
    )
    name = models.CharField(max_length=120)
    interval = models.CharField(max_length=16, choices=Interval.choices)
    custom_days = models.PositiveIntegerField(null=True, blank=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    # ISO 4217 lowercase, the way `payments.Payment.currency` stores it.
    currency = models.CharField(max_length=3, default="usd")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "name"], name="uniq_membership_plan_name"
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0), name="membership_plan_amount_non_negative"
            ),
            # `custom_days` is meaningful for exactly one interval, and required there.
            models.CheckConstraint(
                condition=(
                    Q(interval="custom_days", custom_days__gt=0)
                    | (~Q(interval="custom_days") & Q(custom_days__isnull=True))
                ),
                name="membership_plan_custom_days_matches_interval",
            ),
        ]
        ordering = ["makerspace_id", "name"]

    def save(self, *args, **kwargs):
        self.currency = (self.currency or "").lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.makerspace_id})"


class MembershipTerm(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    membership = models.ForeignKey(
        "makerspaces.MakerspaceMembership", on_delete=models.CASCADE, related_name="terms"
    )
    # PROTECT: a term is the record of what a member was sold; deleting the plan under it
    # would erase the price history behind a real charge. Deactivate plans instead.
    plan = models.ForeignKey(MembershipPlan, on_delete=models.PROTECT, related_name="terms")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    # The ONE renewal charge raised for this term. Money is never deleted, so SET_NULL is
    # only ever reached by the payments purge path; the Payment row itself stays.
    renewal_payment = models.ForeignKey(
        "payments.Payment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="renewed_membership_terms",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_membership_terms",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="membership_term_ends_after_start"
            ),
        ]
        indexes = [
            models.Index(fields=["status", "ends_at"], name="membershipterm_status_ends_idx"),
        ]
        ordering = ["-starts_at", "-pk"]

    def __str__(self):
        return f"term {self.pk} of membership {self.membership_id}"
