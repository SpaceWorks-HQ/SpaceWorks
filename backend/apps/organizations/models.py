from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q


class Organization(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    legal_name = models.CharField(max_length=200, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)
    billing_email = models.EmailField(blank=True)
    logo_key = models.CharField(max_length=300, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    public_profile_enabled = models.BooleanField(default=False)
    makerspaces = models.ManyToManyField(
        "makerspaces.Makerspace",
        through="OrganizationMakerspace",
        # related_name="+" on purpose: the reverse accessor would add an
        # `organizations` relation to Makerspace, which the data-export drift guard
        # then demands a disposition for. The link is already reachable from either
        # side through OrganizationMakerspace (makerspace_links /
        # organization_links), so the extra accessor buys nothing and widens the
        # tenant-export surface.
        related_name="+",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_organizations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self):
        return self.name


class OrganizationMakerspace(models.Model):
    class Relationship(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        AFFILIATE = "affiliate", "Affiliate"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="makerspace_links",
    )
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="organization_links",
    )
    relationship = models.CharField(max_length=16, choices=Relationship.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_organization_makerspace_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "makerspace"),
                name="uniq_organization_makerspace_pair",
            ),
            models.UniqueConstraint(
                fields=("makerspace",),
                condition=Q(relationship="owner"),
                name="uniq_owner_per_makerspace",
            ),
        ]

    def __str__(self):
        return f"{self.organization} {self.get_relationship_display().lower()} of {self.makerspace}"


class OrganizationMembership(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )
    granted_actions = models.JSONField(default=list, blank=True)
    governance_actions = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="uniq_org_membership_user",
            ),
        ]
        indexes = [
            GinIndex(
                fields=["granted_actions"],
                name="orgmembership_actions_gin",
            ),
        ]

    def __str__(self):
        return f"{self.user} in {self.organization}"


class OrganizationInvitation(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    granted_actions = models.JSONField(default=list, blank=True)
    governance_actions = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField()
    redeemed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_organization_invitations",
    )
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="redeemed_organization_invitations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(redeemed_at__isnull=True, redeemed_by__isnull=True)
                    | Q(redeemed_at__isnull=False, redeemed_by__isnull=False)
                ),
                name="org_invitation_redemption_complete",
            ),
            models.CheckConstraint(
                condition=Q(redeemed_at__isnull=True) | Q(revoked_at__isnull=True),
                name="org_invitation_not_redeemed_revoked",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "expires_at"),
                condition=Q(redeemed_at__isnull=True, revoked_at__isnull=True),
                name="org_invitation_active_idx",
            ),
        ]

    def __str__(self):
        return f"Invitation to {self.organization}"
