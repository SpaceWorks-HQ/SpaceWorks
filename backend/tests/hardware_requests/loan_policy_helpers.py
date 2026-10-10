from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
from tests.return_helpers import make_product, make_space, make_user


def setup_loan(slug="policy", *, due_at=None, linked=True):
    space = make_space(slug)
    space.enabled_modules = sorted(set(space.enabled_modules) | {"membership", "notifications", "email", "request_workflow"})
    space.enabled_features = sorted(set(space.enabled_features) | {"loans.renewals", "loans.limits"})
    space.save(update_fields=["enabled_features", "enabled_modules"])
    member = make_user(f"member-{slug}")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=member, assigned_role=role, role="custom")
    product = make_product(space)
    due_at = due_at or timezone.now() + timedelta(days=1)
    request = HardwareRequest.objects.create(
        makerspace=space, requester=member, requester_username=member.username,
        requester_contact_email=member.email, requester_contact_verified=True,
        status="issued", issued_at=timezone.now(), return_due_at=due_at,
    )
    HardwareRequestItem.objects.create(request=request, product=product, requested_quantity=1,
                                       accepted_quantity=1, issued_quantity=1)
    if linked:
        PublicToolLoan.objects.create(makerspace=space, request=request, requester=member,
                                     target_type="direct", target_id=request.pk, target_label=product.name,
                                     source="admin_direct", due_at=due_at)
    policy = MakerspaceLoanPolicy.objects.create(makerspace=space, loan_renewal_mode="auto")
    client = APIClient()
    client.force_authenticate(member)
    return space, member, membership, product, request, policy, client
