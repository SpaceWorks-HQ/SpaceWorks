"""Phone verification challenges -- the twin of EmailVerificationChallenge.

Two purposes are carried by one model, discriminated by `purpose`:

* LINK   -- an authenticated user proving they hold a number, to attach it.
* LOGIN  -- an anonymous caller proving they hold an already-verified number.

Keeping them in one table but distinguishing the purpose is deliberate. A LINK
challenge must never be redeemable at the login endpoint: otherwise a member who
starts linking a number and walks away leaves a code that signs someone in.
"""

from django.db import models


class PhoneChallengePurpose(models.TextChoices):
    LINK = "link", "Link a phone number"
    LOGIN = "login", "Sign in with a phone number"


class PhoneVerificationChallenge(models.Model):
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="phone_challenges"
    )
    purpose = models.CharField(max_length=16, choices=PhoneChallengePurpose.choices)
    # The E.164 number this challenge was issued against, snapshotted. A later edit to
    # the user's number leaves this row unable to match, which is the intended lapse.
    phone_e164 = models.CharField(max_length=20)
    code_digest = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "phone_e164", "expires_at"]),
            models.Index(
                fields=["purpose", "phone_e164"],
                condition=models.Q(consumed_at__isnull=True),
                name="phone_challenge_active_idx",
            ),
        ]

    def is_usable(self, now):
        return (
            self.consumed_at is None
            and self.failed_attempts < 5
            and self.expires_at > now
        )

    def __str__(self):
        return f"{self.purpose} challenge for user {self.user_id}"
