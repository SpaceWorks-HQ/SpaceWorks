import pytest
from django.contrib.auth import get_user_model

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import grant_handout

pytestmark = pytest.mark.django_db


def make_user(username, role=User.Role.REQUESTER, **kw):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@e.com", role=role, **kw
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def test_superadmin_scope_is_all():
    u = make_user("su", role=User.Role.SUPERADMIN)
    assert rbac.resolve_scope(u) is rbac.ALL


def test_admin_scope_is_membership_makerspaces():
    u = make_user("a", role=User.Role.SPACE_MANAGER)
    s1, s2 = make_space("s1"), make_space("s2")
    MakerspaceMembership.objects.create(user=u, makerspace=s1)
    assert rbac.resolve_scope(u) == {s1.id}
    assert s2.id not in rbac.resolve_scope(u)


def test_requester_scope_empty():
    u = make_user("r", role=User.Role.REQUESTER)
    assert rbac.resolve_scope(u) == set()


def test_scope_by_makerspace_filters_other_tenants():
    admin = make_user("a2", role=User.Role.SPACE_MANAGER)
    s1, s2 = make_space("t1"), make_space("t2")
    MakerspaceMembership.objects.create(user=admin, makerspace=s1)
    qs = Makerspace.objects.all()
    scoped = rbac.scope_by_makerspace(admin, qs, makerspace_field="id")
    assert list(scoped) == [s1]


def test_can_matrix_space_manager_vs_front_desk():
    admin = make_user("ad", role=User.Role.SPACE_MANAGER)
    guest = make_user("gu", role=User.Role.REQUESTER)
    s = make_space("m1")
    MakerspaceMembership.objects.create(user=admin, makerspace=s, role="space_manager")
    grant_handout(guest, s)

    assert rbac.can(admin, rbac.Action.ACCEPT_REQUEST, s.id) is True
    assert rbac.can(guest, rbac.Action.ACCEPT_REQUEST, s.id) is False
    assert rbac.can(guest, rbac.Action.ISSUE_REQUEST, s.id) is True
    assert rbac.can(guest, rbac.Action.ISSUE_DIRECT_LOAN, s.id) is True
    assert rbac.can(admin, rbac.Action.EDIT_INVENTORY, s.id) is True
    assert rbac.can(guest, rbac.Action.EDIT_INVENTORY, s.id) is False


def test_can_denies_out_of_scope_makerspace():
    admin = make_user("ad2", role=User.Role.SPACE_MANAGER)
    s1, s2 = make_space("x1"), make_space("x2")
    MakerspaceMembership.objects.create(user=admin, makerspace=s1, role="space_manager")
    assert rbac.can(admin, rbac.Action.ACCEPT_REQUEST, s2.id) is False


def test_superadmin_can_everything_including_transfer():
    su = make_user("s3", role=User.Role.SUPERADMIN)
    s = make_space("z1")
    assert rbac.can(su, rbac.Action.TRANSFER_STOCK, s.id) is True
    assert rbac.can(su, rbac.Action.MANAGE_STAFF, None) is True


def test_admin_cannot_transfer_stock():
    admin = make_user("ad3", role=User.Role.SPACE_MANAGER)
    s = make_space("z2")
    MakerspaceMembership.objects.create(user=admin, makerspace=s, role="space_manager")
    assert rbac.can(admin, rbac.Action.TRANSFER_STOCK, s.id) is False


def test_inventory_manager_gets_full_hardware_actions_only():
    user = make_user("inventory-manager", role=User.Role.REQUESTER)
    makerspace = make_space("inventory-manager-space")
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )

    allowed = {
        rbac.Action.VIEW_INVENTORY,
        rbac.Action.EDIT_INVENTORY,
        rbac.Action.ACCEPT_REQUEST,
        rbac.Action.REJECT_REQUEST,
        rbac.Action.ASSIGN_BOX,
        rbac.Action.ISSUE_REQUEST,
        rbac.Action.RETURN_REQUEST,
        rbac.Action.UPLOAD_EVIDENCE,
        rbac.Action.MANAGE_QR,
        rbac.Action.VIEW_AUDIT,
    }
    denied = {
        rbac.Action.MANAGE_PRINTING,
        rbac.Action.MANAGE_STAFF,
        rbac.Action.MANAGE_MAKERSPACE,
    }

    for action in allowed:
        assert rbac.can(user, action, makerspace.id) is True
    for action in denied:
        assert rbac.can(user, action, makerspace.id) is False


def test_membership_role_overrides_global_role():
    # Globally `space_manager`, but only front-desk staff in THIS makerspace.
    u = make_user("mix", role=User.Role.SPACE_MANAGER)
    s = make_space("mx")
    grant_handout(u, s)
    assert rbac.can(u, rbac.Action.ACCEPT_REQUEST, s.id) is False  # front desk can't accept
    assert rbac.can(u, rbac.Action.ISSUE_REQUEST, s.id) is True    # front desk can issue


def test_non_member_denied_even_with_global_staff_role():
    u = make_user("nm", role=User.Role.SPACE_MANAGER)
    s = make_space("nm1")  # no membership created
    assert rbac.can(u, rbac.Action.VIEW_INVENTORY, s.id) is False


from rest_framework.test import APIRequestFactory

from apps.accounts.permissions import IsSuperadmin, IsStaff


def test_permission_classes_basic():
    rf = APIRequestFactory()
    su = make_user("p1", role=User.Role.SUPERADMIN)
    staff = make_user("p2", role=User.Role.SPACE_MANAGER)
    member = make_user("p3", role=User.Role.REQUESTER)
    req = rf.get("/")
    req.user = su
    assert IsSuperadmin().has_permission(req, None) is True
    req.user = staff
    assert IsSuperadmin().has_permission(req, None) is False
    assert IsStaff().has_permission(req, None) is True
    req.user = member
    assert IsStaff().has_permission(req, None) is False


def test_isstaff_rejects_suspended_after_login():
    rf = APIRequestFactory()
    suspended = make_user("p3", role=User.Role.SPACE_MANAGER,
                          access_status=User.AccessStatus.SUSPENDED)
    req = rf.get("/")
    req.user = suspended
    assert IsStaff().has_permission(req, None) is False


def test_issuperadmin_rejects_suspended_superadmin():
    rf = APIRequestFactory()
    su = make_user("p4", role=User.Role.SUPERADMIN,
                   access_status=User.AccessStatus.SUSPENDED)
    req = rf.get("/")
    req.user = su
    assert IsSuperadmin().has_permission(req, None) is False
