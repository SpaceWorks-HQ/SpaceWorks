from django.apps import apps

MAKERSPACE_KWARG_ROUTES = {
    'admin-maintenance-schedule-list-create': 'makerspace_id',
    'admin-maintenance-log-list-create': 'makerspace_id',
    'admin-bookable-space-list-create': 'makerspace_id',
    'admin-event-list-create': 'makerspace_id',
    'admin-role-capabilities': 'makerspace_id',
    'admin-role-list-create': 'makerspace_id',
    'admin-role-detail': 'makerspace_id',
    'admin-machine-types': 'makerspace_id',
    'admin-machine-type-detail': 'makerspace_id',
    'admin-makerspace-provision-subdomain': 'makerspace_id',
    'admin-makerspace-subdomain-request': 'makerspace_id',
    'admin-api-settings': 'makerspace_id',
    'admin-notification-recipients': 'makerspace_id',
    'admin-notification-rules': 'makerspace_id',
    'admin-machine-service-request-list-create': 'makerspace_id',
}
# These routes have no tenant-bearing path segment by design: each is a listing whose
# queryset is explicitly narrowed by the named makerspace query parameter.
QUERY_SCOPED_ROUTES = {
    'admin-api-key-requests',       # requester-owned API-key requests; ?makerspace=
    'admin-audit-logs',             # tenant audit-log listing; ?makerspace=
    'admin-membership-requests',    # tenant join-request queue; ?makerspace_id=
    'admin-memberships-roster',     # tenant membership roster; ?makerspace_id=
    'admin-needs-fix-shelf',        # tenant repair shelf; ?makerspace=
    'ledger-aggregate',             # superadmin aggregate listing; ?makerspace=
    'ledger-export-aggregate',      # matching aggregate export; ?makerspace=
}
NATIVE_HEADER_GLOBAL_ROUTES = {
    'auth-me',
    'device-grants',
    'device-grant-detail',
    'push-device-list-create',
    'push-device-detail',
}
REQUEST_ACTIONS = {
    'request-accept',
    'request-reject',
    'request-assign-box',
    'request-issue',
    'request-return-due',
    'request-return',
    'guest-admin-request-return',
    'request-timeline',
}
MACHINE_SERVICE_ACTIONS = {
    'admin-machine-service-request-detail',
    'admin-machine-service-request-accept',
    'admin-machine-service-request-reject',
    'admin-machine-service-request-start',
    'admin-machine-service-request-complete',
    'admin-machine-service-request-fail',
    'admin-machine-service-request-collect',
    'admin-machine-service-file-presign',
    'admin-machine-service-file-finalize',
}
MODEL_LOOKUPS = {
    'admin-membership-request-approve': ('makerspaces.MembershipRequest', 'makerspace_id'),
    'admin-membership-request-revoke': ('makerspaces.MembershipRequest', 'makerspace_id'),
    'admin-membership-revoke-m2': ('makerspaces.MakerspaceMembership', 'makerspace_id'),
    'admin-membership-role-m2': ('makerspaces.MakerspaceMembership', 'makerspace_id'),
    'admin-membership-capabilities': ('makerspaces.MakerspaceMembership', 'makerspace_id'),
    'admin-membership-revoke': ('makerspaces.MakerspaceMembership', 'makerspace_id'),
    'admin-presence-sessions-current': ('makerspaces.Makerspace', 'id'),
    'admin-maintenance-schedule-detail': ('maintenance.MaintenanceSchedule', 'machine__makerspace_id'),
    'admin-maintenance-schedule-deactivate': ('maintenance.MaintenanceSchedule', 'machine__makerspace_id'),
    'admin-maintenance-log-document-presign': ('maintenance.MaintenanceLog', 'machine__makerspace_id'),
    'admin-maintenance-log-document-finalize': ('maintenance.MaintenanceLog', 'machine__makerspace_id'),
    'admin-maintenance-log-document-url': ('maintenance.MaintenanceLogDocument', 'log__machine__makerspace_id'),
    'admin-maintenance-log-document-detail': ('maintenance.MaintenanceLogDocument', 'log__machine__makerspace_id'),
    'admin-bookable-space-detail': ('bookings.BookableSpace', 'makerspace_id'),
    'admin-bookable-space-booking-rules': ('bookings.BookableSpace', 'makerspace_id'),
    'admin-bookable-space-deactivate': ('bookings.BookableSpace', 'makerspace_id'),
    'admin-bookable-space-image-presign': ('bookings.BookableSpace', 'makerspace_id'),
    'admin-bookable-space-image-finalize': ('bookings.BookableSpace', 'makerspace_id'),
    'admin-bookable-space-image-delete': ('bookings.BookableSpace', 'makerspace_id'),
    'admin-space-booking-list': ('bookings.BookableSpace', 'makerspace_id'),
    'admin-booking-approve': ('bookings.Booking', 'space__makerspace_id'),
    'admin-booking-reject': ('bookings.Booking', 'space__makerspace_id'),
    'admin-booking-cancel': ('bookings.Booking', 'space__makerspace_id'),
    'admin-booking-complete': ('bookings.Booking', 'space__makerspace_id'),
    'admin-booking-no-show': ('bookings.Booking', 'space__makerspace_id'),
    'admin-event-detail': ('events.Event', 'makerspace_id'),
    'admin-event-publish': ('events.Event', 'makerspace_id'),
    'admin-event-cancel': ('events.Event', 'makerspace_id'),
    'admin-event-complete': ('events.Event', 'makerspace_id'),
    'admin-event-registration-list': ('events.Event', 'makerspace_id'),
    'admin-event-check-in-resolve': ('events.Event', 'makerspace_id'),
    'admin-event-registration-mark-attended': ('events.EventRegistration', 'event__makerspace_id'),
    'admin-event-collaborators': ('events.Event', 'makerspace_id'),
    # Respond belongs to the collaborator's domain; removal belongs to the host's.
    # Resolving respond through the host would make the feature unreachable from the
    # collaborator's custom domain, while resolving removal through the collaborator
    # would give the host route the wrong origin scope.
    'admin-event-collaboration-remove': (
        'events.EventCollaborator', 'event__makerspace_id'
    ),
    'admin-event-collaboration-respond': (
        'events.EventCollaborator', 'makerspace_id'
    ),
    'admin-machine-operator-candidates': ('machines.Machine', 'makerspace_id'),
    'admin-machine-publicity': ('machines.Machine', 'makerspace_id'),
    'makerspace-verify-domain': ('makerspaces.Makerspace', 'id'),
    'admin-inventory-detail': ('inventory.InventoryProduct', 'makerspace_id'),
    'admin-inventory-image': ('inventory.InventoryProduct', 'makerspace_id'),
    'admin-inventory-asset-detail': ('inventory.InventoryAsset', 'makerspace_id'),
    'admin-machine-warranty': ('machines.Machine', 'makerspace_id'),
    'admin-warranty-document-presign': ('warranty.Warranty', 'makerspace_id'),
    'admin-warranty-documents': ('warranty.Warranty', 'makerspace_id'),
    'admin-warranty-document-url': ('warranty.WarrantyDocument', 'warranty__makerspace_id'),
    'admin-warranty-document-detail': ('warranty.WarrantyDocument', 'warranty__makerspace_id'),
    'admin-inventory-adjust-quantity': ('inventory.InventoryProduct', 'makerspace_id'),
    'admin-inventory-lending-history': ('inventory.InventoryProduct', 'makerspace_id'),
    'admin-inventory-chain-of-custody': ('inventory.InventoryProduct', 'makerspace_id'),
    'admin-needs-fix-action': ('inventory.InventoryProduct', 'makerspace_id'),
    'admin-category-detail': ('inventory.Category', 'makerspace_id'),
    'container-detail': ('boxes.Box', 'makerspace_id'),
    'container-move': ('boxes.Box', 'makerspace_id'),
    'container-contents': ('boxes.Box', 'makerspace_id'),
    'container-history': ('boxes.Box', 'makerspace_id'),
    'qr-print': ('boxes.QrCode', 'makerspace_id'),
    'qr-revoke': ('boxes.QrCode', 'makerspace_id'),
    'qr-rebind-target': ('boxes.QrCode', 'makerspace_id'),
    'evidence-detail': ('evidence.EvidencePhoto', 'makerspace_id'),
    'stock-transfer-detail': ('operations.StockTransfer', 'makerspace_id'),
    'stocktake-detail': ('operations.StocktakeSession', 'makerspace_id'),
    'stocktake-count-lines': ('operations.StocktakeSession', 'makerspace_id'),
    'stocktake-resolve-scan': ('operations.StocktakeSession', 'makerspace_id'),
    'stocktake-complete': ('operations.StocktakeSession', 'makerspace_id'),
    'stocktake-approve': ('operations.StocktakeSession', 'makerspace_id'),
    'stocktake-apply-adjustments': ('operations.StocktakeSession', 'makerspace_id'),
    'qr-print-batch-detail': ('operations.QrPrintBatch', 'makerspace_id'),
    'qr-print-batch-items': ('operations.QrPrintBatch', 'makerspace_id'),
    'qr-print-batch-download': ('operations.QrPrintBatch', 'makerspace_id'),
    'direct-loan-return': ('hardware_requests.PublicToolLoan', 'makerspace_id'),
    'problem-report-triage': ('hardware_requests.PublicProblemReport', 'makerspace_id'),
    'to-buy-detail': ('procurement.ToBuyItem', 'makerspace_id'),
    'to-buy-move-to-inventory': ('procurement.ToBuyItem', 'makerspace_id'),
    'to-buy-move-to-printing': ('procurement.ToBuyItem', 'makerspace_id'),
    'to-buy-receipt-presign': ('procurement.ToBuyItem', 'makerspace_id'),
    'to-buy-receipt-list': ('procurement.ToBuyItem', 'makerspace_id'),
    'to-buy-receipt-url': ('procurement.ToBuyReceipt', 'to_buy_item__makerspace_id'),
    'to-buy-receipt-detail': ('procurement.ToBuyReceipt', 'to_buy_item__makerspace_id'),
    'admin-machine-detail': ('machines.Machine', 'makerspace_id'),
    'admin-machine-image': ('machines.Machine', 'makerspace_id'),
    'admin-machine-set-status': ('machines.Machine', 'makerspace_id'),
    'admin-machine-retire': ('machines.Machine', 'makerspace_id'),
    'admin-machine-unretire': ('machines.Machine', 'makerspace_id'),
    'admin-machine-usage': ('machines.Machine', 'makerspace_id'),
    'admin-machine-consumables': ('machines.Machine', 'makerspace_id'),
    'admin-machine-consumable-detail': ('machines.Machine', 'makerspace_id'),
    'admin-machine-consumption-log': ('machines.Machine', 'makerspace_id'),
    'admin-machine-consumable-candidates': ('machines.Machine', 'makerspace_id'),
    'admin-machine-operators': ('machines.Machine', 'makerspace_id'),
    'admin-machine-operator-detail': ('machines.Machine', 'makerspace_id'),
    'admin-machine-document-presign': ('machines.Machine', 'makerspace_id'),
    'admin-machine-documents': ('machines.Machine', 'makerspace_id'),
    'admin-machine-error-logs': ('machines.Machine', 'makerspace_id'),
    'admin-machine-document-url': ('machines.MachineDocument', 'machine__makerspace_id'),
    'admin-machine-document-detail': ('machines.MachineDocument', 'machine__makerspace_id'),
    'admin-machine-service-file-url': ('machines.ServiceRequestFile', 'makerspace_id'),
    'admin-machine-service-file-detail': ('machines.ServiceRequestFile', 'makerspace_id'),
    'admin-machine-service-request-reprint': ('machines.MachineServiceRequest', 'makerspace_id'),
    'admin-machine-service-payment-mark-offline': ('payments.Payment', 'makerspace_id'),
    'admin-machine-service-payment-waive': ('payments.Payment', 'makerspace_id'),
    **{name: ('hardware_requests.HardwareRequest', 'makerspace_id') for name in REQUEST_ACTIONS},
    **{name: ('machines.MachineServiceRequest', 'makerspace_id') for name in MACHINE_SERVICE_ACTIONS},
}
# A password belongs to a User, not one membership. Keep this set-valued lookup out of
# MODEL_LOOKUPS so a multi-membership user can never be reduced to one arbitrary tenant.
TARGET_SET_LOOKUPS = {
    'admin-user-reset-password': (
        'makerspaces.MakerspaceMembership', 'user_id', 'makerspace_id'),
}


def request_route_targets(request, view=None):
    url_name, targets, invalid, route_recognized = _authoritative_route_targets(
        request, view
    )
    hints = []

    query = getattr(request, 'query_params', None)
    if query is None:
        query = getattr(request, 'GET', {})
    for key in ('makerspace', 'makerspace_id'):
        value = query.get(key)
        if value in (None, ''):
            continue
        parsed = _positive_int(value)
        invalid = invalid or parsed is None
        if parsed is not None:
            hints.append(parsed)

    if getattr(request, "method", "GET") not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        body = getattr(request, "data", {})
        if hasattr(body, "get"):
            for key in ("makerspace", "makerspace_id"):
                value = body.get(key)
                if value in (None, ""):
                    continue
                parsed = _positive_int(value)
                invalid = invalid or parsed is None
                if parsed is not None:
                    hints.append(parsed)

    hint_set = set(hints)
    if url_name in TARGET_SET_LOOKUPS:
        invalid = invalid or bool(hint_set - targets)
    else:
        invalid = invalid or len(targets | hint_set) > 1
    target_set = targets | hint_set
    return url_name, target_set, invalid, route_recognized


def authoritative_route_resolution(request, view=None):
    """Return non-raising authoritative targets plus whether the route is known."""
    try:
        _name, targets, invalid, recognized = _authoritative_route_targets(
            request, view
        )
    except Exception:
        return set(), False
    return (targets if recognized and not invalid else set()), recognized


def _authoritative_route_targets(request, view=None):
    match = getattr(request, 'resolver_match', None)
    url_name = getattr(match, 'url_name', '')
    kwargs = dict(getattr(match, 'kwargs', {}) or {})
    kwargs.update(getattr(view, 'kwargs', {}) or {})
    targets = set()
    invalid = False
    registered = MAKERSPACE_KWARG_ROUTES.get(url_name)
    route_recognized = bool(
        registered or 'makerspace_id' in kwargs
        or (url_name == 'admin-makerspace' and 'pk' in kwargs)
        or url_name in MODEL_LOOKUPS or url_name in TARGET_SET_LOOKUPS
        or url_name in QUERY_SCOPED_ROUTES or url_name in NATIVE_HEADER_GLOBAL_ROUTES)
    route_value = None
    if registered:
        route_value = kwargs.get(registered)
        invalid = route_value is None
    elif 'makerspace_id' in kwargs:
        route_value = kwargs.get('makerspace_id')
    elif url_name == 'admin-makerspace' and 'pk' in kwargs:
        route_value = kwargs.get('pk')
    if route_value is not None:
        parsed = _positive_int(route_value)
        invalid = invalid or parsed is None
        if parsed is not None:
            targets.add(parsed)

    if url_name in MODEL_LOOKUPS:
        pk = kwargs.get('pk')
        resolved = _lookup_makerspace_id(url_name, pk) if pk is not None else None
        invalid = invalid or resolved is None
        if resolved is not None:
            targets.add(resolved)
    elif url_name in TARGET_SET_LOOKUPS:
        pk = kwargs.get('pk')
        invalid = invalid or pk is None
        if pk is not None:
            targets.update(_lookup_makerspace_ids(url_name, pk))
    return url_name, targets, invalid, route_recognized


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 and str(parsed) == str(value).strip() else None


def _lookup_makerspace_id(url_name, pk):
    model_path, field = MODEL_LOOKUPS[url_name]
    model = apps.get_model(model_path)
    try:
        return model.objects.values_list(field, flat=True).get(pk=pk)
    except model.DoesNotExist:
        return None


def _lookup_makerspace_ids(url_name, pk):
    model_path, owner_field, tenant_field = TARGET_SET_LOOKUPS[url_name]
    model = apps.get_model(model_path)
    return set(
        model.objects.filter(**{owner_field: pk})
        .values_list(tenant_field, flat=True)
    )
