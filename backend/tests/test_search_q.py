"""The one `?q=` contract: full-text + trigram over trigger-maintained vectors, tenant-scoped."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.events.models import Event
from apps.inventory.models import InventoryProduct
from apps.inventory.search import apply_q, clean_query
from apps.machines.models import Machine, MachineType
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


def test_trigger_fills_the_vector_on_insert_and_update():
    space = make_space("fts-space")
    product = make_product(space, name="Cordless Drill", description="18V hammer drill")
    product.refresh_from_db()
    assert product.search_vector is not None
    assert "drill" in str(product.search_vector)
    InventoryProduct.objects.filter(pk=product.pk).update(name="Angle Grinder")
    product.refresh_from_db()
    assert "grinder" in str(product.search_vector)
    assert "cordless" not in str(product.search_vector)


def test_apply_q_matches_words_phrases_and_typos_and_ranks_the_label_first():
    space = make_space("fts-rank")
    make_product(space, name="Soldering Iron", description="temperature controlled")
    make_product(space, name="Heat Gun", description="for soldering heat shrink")
    make_product(space, name="Multimeter")
    names = lambda q: list(apply_q(InventoryProduct.objects.filter(makerspace=space), q).values_list("name", flat=True))
    assert names("soldering") == ["Soldering Iron", "Heat Gun"]  # label (A) outranks description (D)
    assert names("soldring") == ["Soldering Iron"]  # trigram catches the typo on the label
    assert names('"heat shrink"') == ["Heat Gun"]
    assert names("multimeter") == ["Multimeter"]
    assert names("solder") == ["Soldering Iron", "Heat Gun"]  # plain words match as prefixes
    assert names("temp contr") == ["Soldering Iron"]
    # A blank query leaves the queryset untouched (and unordered by rank).
    assert set(names("   ")) == {"Heat Gun", "Multimeter", "Soldering Iron"}
    assert len(clean_query("x" * 500)) == 200


def test_public_inventory_search_is_tenant_scoped():
    alpha, beta = make_space("fts-alpha"), make_space("fts-beta")
    make_product(alpha, name="Laser Cutter Goggles")
    make_product(beta, name="Laser Cutter Goggles")
    make_product(alpha, name="Bandsaw")
    url = reverse("public-inventory", kwargs={"makerspace_slug": alpha.slug})
    payload = APIClient().get(url, {"q": "laser goggles"}).json()
    assert payload["count"] == 1
    assert payload["results"][0]["name"] == "Laser Cutter Goggles"
    payload = APIClient().get(url, {"q": "bandsaw"}).json()
    assert [row["name"] for row in payload["results"]] == ["Bandsaw"]


def test_admin_inventory_search_still_matches_category_name():
    from apps.inventory.models import Category

    space = make_space("fts-admin")
    manager = make_member("fts-admin-manager", space)
    category = Category.objects.create(makerspace=space, name="Woodworking", slug="woodworking")
    make_product(space, name="Chisel Set", category=category)
    make_product(space, name="Oscilloscope")
    client = authenticated_client(manager)
    url = reverse("admin-inventory", kwargs={"makerspace_id": space.pk})
    by_category = client.get(url, {"q": "woodworking"}).json()
    assert [row["name"] for row in by_category["results"]] == ["Chisel Set"]
    by_name = client.get(url, {"q": "chisel"}).json()
    assert [row["name"] for row in by_name["results"]] == ["Chisel Set"]


def test_machine_and_event_search():
    space = make_space("fts-machines")
    manager = make_member("fts-machine-manager", space)
    mtype = MachineType.objects.create(makerspace=space, name="Printers", slug="printers")
    Machine.objects.create(makerspace=space, machine_type=mtype, name="Prusa MK4", location="Bench 2", is_public=True)
    Machine.objects.create(makerspace=space, machine_type=mtype, name="Bambu X1", location="Bench 3", is_public=True)
    machines = apply_q(Machine.objects.filter(makerspace=space), "prusa")
    assert list(machines.values_list("name", flat=True)) == ["Prusa MK4"]
    assert list(apply_q(Machine.objects.filter(makerspace=space), "bench 3").values_list("name", flat=True)) == ["Bambu X1"]

    start = timezone.now() + timedelta(days=2)
    Event.objects.create(makerspace=space, title="Intro to Laser Cutting", starts_at=start, ends_at=start + timedelta(hours=2), is_public=True, status=Event.Status.PUBLISHED)
    Event.objects.create(makerspace=space, title="Sewing Circle", starts_at=start, ends_at=start + timedelta(hours=2), is_public=True, status=Event.Status.PUBLISHED)
    events = apply_q(Event.objects.filter(makerspace=space), "laser", label_field="title")
    assert list(events.values_list("title", flat=True)) == ["Intro to Laser Cutting"]
    client = authenticated_client(manager)
    url = reverse("admin-event-list-create", kwargs={"makerspace_id": space.pk})
    payload = client.get(url, {"q": "sewing"}).json()
    titles = [row["title"] for row in payload["results"]]
    assert titles == ["Sewing Circle"]
