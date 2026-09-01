"""Which ways in this deployment offers, as one superadmin-owned singleton.

Platform-scoped and deliberately never a tenant feature, for the reason that already
keeps social sign-in off the capability registry: every one of these resolves *before* a
makerspace is selected, so a per-tenant key would be unreachable at the moment it must be
answered and would read as disabled for everyone.

All four default **on**, so introducing them changes nothing for an existing deployment.
They are additive `AND`s in front of the readiness each method already had -- switching
one on can never make an unconfigured method start working, and switching one off never
touches the stored credentials, so re-enabling needs no re-entry.

`accounts` (the module) and these switches answer different questions and compose:
`accounts` says whether this deployment runs a member-account ecosystem at all, while
these say which credentials the deployment accepts. Self sign-up needs both.
"""

from django.db import models


class PlatformLoginMethods(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    password_enabled = models.BooleanField(
        default=True,
        help_text="Username/email and password sign-in, for staff and members alike.",
    )
    social_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Sign-in through an identity provider — the built-in Google and Apple "
            "providers and every configured OIDC provider. They share one endpoint, so "
            "they share one switch."
        ),
    )
    phone_enabled = models.BooleanField(
        default=True, help_text="Sign-in with an SMS code to a verified number."
    )
    self_registration_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Whether anyone may create their own member account. With this off, staff "
            "add people from the console."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform login methods"
        verbose_name_plural = "Platform login methods"

    def __str__(self):
        return "Platform login methods"

    @classmethod
    def load(cls):
        """The stored row, or an unsaved default.

        Deliberately does NOT `get_or_create`: this is read on every login attempt, and
        a read path that writes turns an unauthenticated request into a database write.
        An absent row means "nothing configured", which is every switch on.
        """
        return cls.objects.filter(pk=1).first() or cls()
