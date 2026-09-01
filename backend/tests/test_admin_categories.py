import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.inventory.models import Category, InventoryProduct
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_product,
    make_space,
)
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def category_list_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/categories"


def category_detail_url(category):
    return f"/api/v1/admin/categories/{category.id}"


def inventory_list_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/inventory"


def inventory_detail_url(product):
    return f"/api/v1/admin/inventory/{product.id}"


def make_category(makerspace, name="Tools", slug="tools", **overrides):
    defaults = {"makerspace": makerspace, "name": name, "slug": slug}
    defaults.update(overrides)
    return Category.objects.create(**defaults)


def test_space_manager_creates_category_with_auto_slug():
    makerspace = make_space("category-create")
    admin = make_member("category-create-admin", makerspace)

    response = authenticated_client(admin).post(
        category_list_url(makerspace),
        {"name": "Hand Tools", "display_order": 2, "icon": "wrench"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["slug"] == "hand-tools"
    assert response.data["makerspace"] == makerspace.id
    assert response.data["product_count"] == 0
    assert Category.objects.filter(makerspace=makerspace, slug="hand-tools").exists()
    assert AuditLog.objects.filter(action="category.created").exists()


def test_inventory_manager_can_create_patch_and_delete_category():
    makerspace = make_space("category-inventory-manager")
    manager = make_member(
        "category-inventory-manager-user",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    client = authenticated_client(manager)

    created = client.post(
        category_list_url(makerspace),
        {"name": "Electronics"},
        format="json",
    )
    assert created.status_code == 201

    patched = client.patch(
        f"/api/v1/admin/categories/{created.data['id']}",
        {"name": "Shop Electronics", "slug": "shop-electronics"},
        format="json",
    )
    deleted = client.delete(f"/api/v1/admin/categories/{created.data['id']}")

    assert patched.status_code == 200
    assert patched.data["slug"] == "shop-electronics"
    assert deleted.status_code == 204
    assert not Category.objects.filter(pk=created.data["id"]).exists()


def test_duplicate_slug_in_same_makerspace_is_rejected():
    makerspace = make_space("category-dup")
    admin = make_member("category-dup-admin", makerspace)
    make_category(makerspace, name="Existing", slug="tools")

    response = authenticated_client(admin).post(
        category_list_url(makerspace),
        {"name": "Tools", "slug": "tools"},
        format="json",
    )

    assert response.status_code == 400
    assert "slug" in response.data


def test_same_slug_is_allowed_in_different_makerspaces():
    space_a = make_space("category-same-a")
    space_b = make_space("category-same-b")
    admin_b = make_member("category-same-admin-b", space_b)
    make_category(space_a, name="Tools", slug="tools")

    response = authenticated_client(admin_b).post(
        category_list_url(space_b),
        {"name": "Tools", "slug": "tools"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["slug"] == "tools"


def test_guest_admin_cannot_create_category():
    makerspace = make_space("category-guest-create")
    guest = make_handout_member("category-guest-create-user", makerspace)

    response = authenticated_client(guest).post(
        category_list_url(makerspace),
        {"name": "Blocked"},
        format="json",
    )

    assert response.status_code == 403
    assert not Category.objects.filter(makerspace=makerspace, name="Blocked").exists()


def test_out_of_tenant_category_detail_is_not_found():
    own_space = make_space("category-own")
    other_space = make_space("category-other")
    admin = make_member("category-own-admin", own_space)
    category = make_category(other_space, name="Other", slug="other")

    response = authenticated_client(admin).get(category_detail_url(category))

    assert response.status_code == 404


def test_guest_admin_patch_in_tenant_is_forbidden_not_hidden():
    makerspace = make_space("category-guest-patch")
    guest = make_handout_member("category-guest-patch-user", makerspace)
    category = make_category(makerspace, name="Visible", slug="visible")

    response = authenticated_client(guest).patch(
        category_detail_url(category),
        {"name": "Blocked"},
        format="json",
    )

    assert response.status_code == 403
    category.refresh_from_db()
    assert category.name == "Visible"


def test_delete_category_detaches_products_and_records_count():
    makerspace = make_space("category-delete")
    admin = make_member("category-delete-admin", makerspace)
    category = make_category(makerspace, name="Detach", slug="detach")
    product = make_product(makerspace, name="Scope", category=category)

    response = authenticated_client(admin).delete(category_detail_url(category))

    assert response.status_code == 204
    product.refresh_from_db()
    assert product.category_id is None
    log = AuditLog.objects.get(action="category.deleted")
    assert log.meta == {"detached_product_count": 1}


def test_product_create_and_patch_accept_same_makerspace_category():
    makerspace = make_space("category-product-ok")
    admin = make_member("category-product-ok-admin", makerspace)
    category = make_category(makerspace, name="Meters", slug="meters")
    product = make_product(makerspace, name="Uncategorized")
    client = authenticated_client(admin)

    created = client.post(
        inventory_list_url(makerspace),
        {
            "name": "Multimeter",
            "category": category.id,
            "total_quantity": 2,
            "available_quantity": 2,
        },
        format="json",
    )
    patched = client.patch(
        inventory_detail_url(product),
        {"category": category.id},
        format="json",
    )

    assert created.status_code == 201
    assert created.data["category"] == category.id
    assert patched.status_code == 200
    assert patched.data["category"] == category.id
    product.refresh_from_db()
    assert product.category_id == category.id


def test_product_rejects_cross_makerspace_category():
    space_a = make_space("category-product-a")
    space_b = make_space("category-product-b")
    admin = make_member("category-product-admin", space_a)
    category_b = make_category(space_b, name="Other", slug="other")
    product = make_product(space_a, name="Local")
    client = authenticated_client(admin)

    created = client.post(
        inventory_list_url(space_a),
        {
            "name": "Blocked",
            "category": category_b.id,
            "total_quantity": 1,
            "available_quantity": 1,
        },
        format="json",
    )
    patched = client.patch(
        inventory_detail_url(product),
        {"category": category_b.id},
        format="json",
    )

    assert created.status_code == 400
    assert patched.status_code == 400
    assert (
        InventoryProduct.objects.filter(makerspace=space_a, name="Blocked").count() == 0
    )
    product.refresh_from_db()
    assert product.category_id is None


def test_category_detail_put_is_not_allowed():
    makerspace = make_space("category-put")
    admin = make_member("category-put-admin", makerspace)
    category = make_category(makerspace, name="No Put", slug="no-put")

    response = authenticated_client(admin).put(
        category_detail_url(category),
        {"name": "Still No Put"},
        format="json",
    )

    assert response.status_code == 405
