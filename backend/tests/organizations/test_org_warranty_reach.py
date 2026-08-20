import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.inventory.models import InventoryAsset
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.warranty.models import Warranty, WarrantyDocument
from tests.organizations.test_org_authority import (
    grant,
    link,
    make_makerspace,
    make_organization,
    make_user,
)
from tests.return_helpers import make_product


pytestmark = pytest.mark.django_db


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def _org_editor(slug, makerspace):
    actor = make_user(f"{slug}-editor")
    organization = make_organization(f"{slug}-org")
    link(organization, makerspace, "manager")
    grant(organization, actor, [rbac.Action.EDIT_INVENTORY])
    return actor


def _local_without_actions(slug, makerspace):
    actor = make_user(f"{slug}-local")
    role = MakerspaceRole.objects.create(
        makerspace=makerspace, name=slug, slug=slug, granted_actions=[]
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return actor


def _hosts(makerspace, slug):
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=make_product(makerspace),
        asset_tag=f"{slug}-asset",
    )
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug=f"{slug}-type", name=f"{slug} type"
    )
    machine = Machine.objects.create(
        makerspace=makerspace, machine_type=machine_type, name=f"{slug} machine"
    )
    asset_warranty = Warranty.objects.create(makerspace=makerspace, asset=asset)
    machine_warranty = Warranty.objects.create(makerspace=makerspace, machine=machine)
    asset_document = WarrantyDocument.objects.create(
        warranty=asset_warranty,
        object_key=f"warranty/{makerspace.id}/{slug}-asset.pdf",
        original_filename="asset.pdf",
        content_type="application/pdf",
        size_bytes=12,
    )
    machine_document = WarrantyDocument.objects.create(
        warranty=machine_warranty,
        object_key=f"warranty/{makerspace.id}/{slug}-machine.pdf",
        original_filename="machine.pdf",
        content_type="application/pdf",
        size_bytes=12,
    )
    return asset, machine, asset_warranty, machine_warranty, asset_document, machine_document


def _report_url(makerspace):
    return reverse("admin-makerspace-warranties", args=[makerspace.id])


def test_org_inventory_authority_reaches_assets_but_never_machine_warranties(
    monkeypatch,
):
    makerspace = make_makerspace("org-warranty")
    foreign_space = make_makerspace("org-warranty-foreign")
    actor = _org_editor("org-warranty", makerspace)
    (
        asset,
        machine,
        asset_warranty,
        machine_warranty,
        asset_document,
        machine_document,
    ) = _hosts(makerspace, "org-warranty")
    foreign_asset, *_rest = _hosts(foreign_space, "org-warranty-foreign")
    monkeypatch.setattr(
        "apps.warranty.storage.presigned_get_url", lambda key: "https://signed.test/doc"
    )
    client = _client(actor)

    assert client.get(
        reverse("admin-asset-warranty", args=[asset.id])
    ).status_code == 200
    documents = client.get(
        reverse("admin-warranty-documents", args=[asset_warranty.id])
    )
    assert documents.status_code == 200
    assert {row["id"] for row in documents.data} == {asset_document.id}
    assert client.get(
        reverse("admin-warranty-document-url", args=[asset_document.id])
    ).status_code == 200

    report = client.get(_report_url(makerspace))
    assert report.status_code == 200
    assert {(row["host_kind"], row["host_id"]) for row in report.data["results"]} == {
        ("asset", asset.id)
    }
    assert client.get(
        reverse("admin-asset-warranty", args=[foreign_asset.id])
    ).status_code == 404
    assert client.get(
        reverse("admin-machine-warranty", args=[machine.id])
    ).status_code == 404
    assert client.get(
        reverse("admin-warranty-documents", args=[machine_warranty.id])
    ).status_code == 403
    assert client.get(
        reverse("admin-warranty-document-url", args=[machine_document.id])
    ).status_code == 403


def test_warranty_report_uses_explicit_mixed_authority_and_visibility_statuses():
    makerspace = make_makerspace("org-warranty-status")
    asset, _machine, warranty, _machine_warranty, document, _machine_doc = _hosts(
        makerspace, "org-warranty-status"
    )
    authorized = _org_editor("org-warranty-status", makerspace)
    local = _local_without_actions("org-warranty-status-local", makerspace)
    outsider = make_user("org-warranty-status-outsider")

    assert _client(authorized).get(_report_url(makerspace)).status_code == 200
    assert _client(local).get(_report_url(makerspace)).status_code == 403
    assert _client(outsider).get(_report_url(makerspace)).status_code == 404
    direct_urls = (
        reverse("admin-asset-warranty", args=[asset.id]),
        reverse("admin-warranty-documents", args=[warranty.id]),
        reverse("admin-warranty-document-url", args=[document.id]),
    )
    for url in direct_urls:
        assert _client(local).get(url).status_code == 403
        assert _client(outsider).get(url).status_code == 404

    hidden = make_makerspace(
        "org-warranty-status-hidden", superadmin_access_enabled=False
    )
    hidden_hosts = _hosts(hidden, "org-warranty-hidden")
    hidden_actor = _org_editor("org-warranty-hidden", hidden)
    assert _client(hidden_actor).get(_report_url(hidden)).status_code == 404
    hidden_urls = (
        reverse("admin-asset-warranty", args=[hidden_hosts[0].id]),
        reverse("admin-warranty-documents", args=[hidden_hosts[2].id]),
        reverse("admin-warranty-document-url", args=[hidden_hosts[4].id]),
    )
    for url in hidden_urls:
        assert _client(hidden_actor).get(url).status_code == 404
    archived = make_makerspace("org-warranty-status-archived")
    archived_hosts = _hosts(archived, "org-warranty-archived")
    archived_actor = _org_editor("org-warranty-archived", archived)
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    assert _client(archived_actor).get(_report_url(archived)).status_code == 404
    archived_urls = (
        reverse("admin-asset-warranty", args=[archived_hosts[0].id]),
        reverse("admin-warranty-documents", args=[archived_hosts[2].id]),
        reverse("admin-warranty-document-url", args=[archived_hosts[4].id]),
    )
    for url in archived_urls:
        assert _client(archived_actor).get(url).status_code == 404
