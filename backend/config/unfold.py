import os

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from apps.separability.tombstones import tombstoned_app_labels

SITE_NAME = os.environ.get("ADMIN_SITE_NAME", "Space Works")


def _is_active_superuser(request):
    user = getattr(request, "user", None)
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.is_superuser
        and getattr(user, "access_status", None)
        == getattr(getattr(user, "AccessStatus", None), "ACTIVE", "active")
    )


def _item(title, icon, route, app_label=None):
    """Build one sidebar entry, or None when its app has been tombstoned.

    Omitted rather than permission-hidden, which would not be enough: Unfold calls
    `str(link)` on every item to compute `active` *before* it consults the permission
    callback, so a `reverse_lazy` pointing at a route a tombstoned app no longer
    registers raises NoReverseMatch and 500s the entire console. `_prune_navigation`
    drops the Nones once the literal below is built.

    The tombstone list is read from the environment rather than from settings, because
    settings imports *this* module -- see `tombstones.tombstoned_app_labels`.

    `route` and `separable_app` are carried on the item so the drift-guard test can
    read them back. Unfold copies items through and only ever reads keys it knows, so
    the extra pair is inert.
    """
    if app_label is not None and app_label in tombstoned_app_labels():
        return None
    # Every admin model is superadmin-only (U-SEC), so a single permission gate
    # applies to the whole sidebar.
    return {
        "title": _(title),
        "icon": icon,
        "link": reverse_lazy(route),
        "permission": _is_active_superuser,
        "route": route,
        "separable_app": app_label,
    }


def _managed_active_superuser(request):
    return bool(os.environ.get("PLATFORM_DOMAIN_SUFFIX", "").strip()) and _is_active_superuser(request)


def _managed_item(title, icon, route, app_label=None):
    item = _item(title, icon, route, app_label=app_label)
    if item is None:
        # `_item` returns None for a tombstoned app; subscripting it here would turn a
        # supported tombstone into a boot crash.
        return None
    item["permission"] = _managed_active_superuser
    return item


UNFOLD = {
    "SITE_TITLE": SITE_NAME,
    "SITE_HEADER": SITE_NAME,
    "SITE_SYMBOL": "inventory_2",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "THEME": "dark",
    "COLORS": {
        "primary": {
            "50": "245 243 255",
            "100": "237 233 254",
            "200": "221 214 254",
            "300": "196 181 253",
            "400": "167 139 250",
            "500": "139 92 246",
            "600": "124 58 237",
            "700": "109 40 217",
            "800": "91 33 182",
            "900": "76 29 149",
            "950": "46 16 101",
        }
    },
    "SIDEBAR": {
        "show_search": True,
        "navigation": [
            {
                "title": _("Inventory"),
                "separator": True,
                "items": [
                    _item(
                        "Organizations",
                        "corporate_fare",
                        "admin:organizations_organization_changelist",
                    ),
                    _item(
                        "Organization memberships",
                        "group",
                        "admin:organizations_organizationmembership_changelist",
                    ),
                    _item("Makerspaces", "store", "admin:makerspaces_makerspace_changelist"),
                    _item("Archive requests", "archive", "admin:makerspaces_makerspacearchiverequest_changelist"),
                    _item("Inventory", "inventory_2", "admin:inventory_inventoryproduct_changelist"),
                    _item("Categories", "category", "admin:inventory_category_changelist"),
                    _item("Asset units", "qr_code_2", "admin:inventory_inventoryasset_changelist"),
                    _item("Containers", "package_2", "admin:boxes_box_changelist"),
                    _item("Inventory adjustments", "tune", "admin:operations_inventoryadjustment_changelist"),
                    _item("Warranties", "verified", "admin:warranty_warranty_changelist", app_label="warranty"),
                    _item("Warranty documents", "description", "admin:warranty_warrantydocument_changelist", app_label="warranty"),
                ],
            },
            {
                "title": _("Requests & loans"),
                "separator": True,
                "items": [
                    _item("Hardware requests", "assignment", "admin:hardware_requests_hardwarerequest_changelist"),
                    _item("Tool loans", "outbound", "admin:hardware_requests_publictoolloan_changelist"),
                    _item("Return events", "assignment_return", "admin:hardware_requests_returnevent_changelist"),
                    _item("Accountability", "gavel", "admin:hardware_requests_requesteraccountability_changelist"),
                    _item("Issued asset links", "link", "admin:hardware_requests_hardwarerequestitemasset_changelist"),
                ],
            },
            {
                "title": _("Operations"),
                "separator": True,
                "items": [
                    _item("Stock transfers", "swap_horiz", "admin:operations_stocktransfer_changelist"),
                    _item("Stocktakes", "fact_check", "admin:operations_stocktakesession_changelist"),
                    _item("QR print batches", "print", "admin:operations_qrprintbatch_changelist"),
                    _item("QR codes", "qr_code", "admin:boxes_qrcode_changelist"),
                    _item("QR scans", "barcode_reader", "admin:boxes_qrscanevent_changelist"),
                    _item("Box scans", "qr_code_scanner", "admin:boxes_boxscan_changelist"),
                ],
            },
            {
                "title": _("Procurement"),
                "separator": True,
                "items": [
                    _item("To-buy list", "shopping_cart", "admin:procurement_tobuyitem_changelist", app_label="procurement"),
                ],
            },
            {
                "title": _("Machines"),
                "separator": True,
                "items": [
                    _item("Machines", "precision_manufacturing", "admin:machines_machine_changelist"),
                    _item("Machine types", "category", "admin:machines_machinetype_changelist"),
                    _item("Machine operators", "engineering", "admin:machines_machineoperator_changelist"),
                    _item("Usage entries", "timelapse", "admin:machines_machineusageentry_changelist"),
                    _item("Machine consumables", "deployed_code", "admin:machines_machineconsumable_changelist"),
                    _item("Machine documents", "description", "admin:machines_machinedocument_changelist"),
                    _item("Machine error logs", "error", "admin:machines_machineerrorlog_changelist"),
                    _item("Service buckets", "folder", "admin:machines_servicebucket_changelist"),
                    _item("Service requests", "build", "admin:machines_machineservicerequest_changelist"),
                    _item("Service request files", "attach_file", "admin:machines_servicerequestfile_changelist"),
                    _item("Service consumption", "receipt_long", "admin:machines_servicerequestconsumption_changelist"),
                ],
            },
            {
                "title": _("Accounts & access"),
                "separator": True,
                "items": [
                    _item("Users", "person", "admin:accounts_user_changelist"),
                    _item("Staff memberships", "badge", "admin:makerspaces_makerspacemembership_changelist"),
                    _item("Groups", "groups", "admin:auth_group_changelist"),
                ],
            },
            {
                "title": _("Integrations"),
                "separator": True,
                "items": [
                    _item("API clients", "vpn_key", "admin:apiclients_apiclient_changelist"),
                    _item("API key requests", "approval", "admin:apiclients_apikeyrequest_changelist"),
                    _item("Subdomain requests", "dns", "admin:makerspaces_subdomainrequest_changelist"),
                    _item("Platform email", "mail", "admin:integrations_platformemailsettings_changelist"),
                    _item("Software updates", "system_update", "admin:updates_platformupdatesettings_changelist", app_label="updates"),
                    _item("Payments", "payments", "admin:payments_makerspacepaymentsettings_changelist", app_label="payments"),
                    _managed_item("Stripe Connect", "account_balance", "admin:payments_platformstripeconnectsettings_changelist", app_label="payments"),
                    _item("Email templates", "mail", "admin:integrations_emailtemplate_changelist"),
                    _item("Email logs", "mark_email_read", "admin:integrations_emaillog_changelist"),
                    _item("Email mutes", "notifications_off", "admin:integrations_emailnotificationmute_changelist"),
                ],
            },
            {
                "title": _("Audit & evidence"),
                "separator": True,
                "items": [
                    _item("Audit log", "history", "admin:audit_auditlog_changelist"),
                    _item("Evidence photos", "photo_library", "admin:evidence_evidencephoto_changelist"),
                ],
            },
        ],
    },
}


def _prune_navigation(unfold):
    """Drop the entries `_item` returned None for, and any group left empty.

    A group whose every item belonged to tombstoned apps would otherwise render as a
    bare heading with a separator under it.
    """
    sidebar = unfold["SIDEBAR"]
    sidebar["navigation"] = [
        {**group, "items": kept}
        for group in sidebar["navigation"]
        if (kept := [item for item in group["items"] if item is not None])
    ]
    return unfold


_prune_navigation(UNFOLD)
