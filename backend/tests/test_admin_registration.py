from types import SimpleNamespace

from django.contrib import admin
from django.urls import NoReverseMatch

from apps.separability.tombstones import SEPARABLE_APPS
from config.unfold import UNFOLD
from apps.accounts.models import User
from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.audit.models import AuditLog
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItemAsset, PublicToolLoan, RequesterAccountability, ReturnEvent
from apps.integrations.models import EmailTemplate, MachineTypeEmailTemplate
from apps.inventory.models import Category, InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceArchiveRequest, MakerspaceMembership
from apps.notifications.models import Notification
from apps.operations.models import InventoryAdjustment, QrPrintBatch, StockTransfer, StocktakeSession
from apps.procurement.models import ToBuyItem


def test_core_models_are_registered_in_django_admin():
    registered_models = {Makerspace, MakerspaceArchiveRequest, MakerspaceMembership, Category, InventoryProduct, InventoryAsset, Box, BoxScan, QrCode, QrScanEvent, HardwareRequest, EmailTemplate, MachineTypeEmailTemplate, PublicToolLoan, ReturnEvent, RequesterAccountability, HardwareRequestItemAsset, StockTransfer, StocktakeSession, InventoryAdjustment, QrPrintBatch, ApiClient, ApiKeyRequest, AuditLog, EvidencePhoto, ToBuyItem, User}
    assert registered_models <= set(admin.site._registry)


def test_immutable_admins_are_read_only():
    request = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
    for model in (PublicToolLoan, ReturnEvent, RequesterAccountability, HardwareRequestItemAsset, BoxScan):
        model_admin = admin.site._registry[model]
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False


def test_unfold_sidebar_links_all_resolve():
    broken = []
    for group in UNFOLD["SIDEBAR"]["navigation"]:
        for item in group["items"]:
            try:
                str(item["link"])
            except NoReverseMatch:
                broken.append(str(item["title"]))
    assert broken == []


def test_every_sidebar_entry_owned_by_a_separable_app_declares_it():
    """A sidebar item is the one surface a tombstone cannot merely permission-hide.

    Unfold calls `str(link)` on every item to compute `active` *before* it consults
    the permission callback, so an entry left in place for a tombstoned app raises
    NoReverseMatch and 500s the whole console. `_item(..., app_label=...)` is what
    drops the entry at build time; this asserts nobody adds an entry for a separable
    app without that argument. It grows teeth as SEPARABLE_APPS grows, one phase at
    a time.
    """
    undeclared = [
        item["route"]
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
        if item["separable_app"] is None
        and any(item["route"].startswith(f"admin:{app}_") for app in SEPARABLE_APPS)
    ]
    assert undeclared == []


def test_the_sidebar_declarations_name_real_separable_apps():
    """A stale label silently stops matching, and the entry becomes ungated again."""
    declared = {
        item["separable_app"]
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
        if item["separable_app"] is not None
    }
    assert declared <= SEPARABLE_APPS
