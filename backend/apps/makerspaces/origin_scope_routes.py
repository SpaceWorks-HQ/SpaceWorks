from django.apps import apps


MAKERSPACE_KWARG_ROUTES = {
    'admin-memberships-roster': 'makerspace_id',
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
    **{name: ('hardware_requests.HardwareRequest', 'makerspace_id') for name in REQUEST_ACTIONS},
    **{name: ('machines.MachineServiceRequest', 'makerspace_id') for name in MACHINE_SERVICE_ACTIONS},
}


def request_route_targets(request, view=None):
    match = getattr(request, 'resolver_match', None)
    url_name = getattr(match, 'url_name', '')
    kwargs = dict(getattr(match, 'kwargs', {}) or {})
    kwargs.update(getattr(view, 'kwargs', {}) or {})
    targets = []
    invalid = False

    registered = MAKERSPACE_KWARG_ROUTES.get(url_name)
    route_recognized = bool(
        registered
        or 'makerspace_id' in kwargs
        or (url_name == 'admin-makerspace' and 'pk' in kwargs)
        or url_name in MODEL_LOOKUPS
        or url_name in NATIVE_HEADER_GLOBAL_ROUTES
    )
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
            targets.append(parsed)

    query = getattr(request, 'query_params', {})
    for key in ('makerspace', 'makerspace_id'):
        value = query.get(key)
        if value in (None, ''):
            continue
        parsed = _positive_int(value)
        invalid = invalid or parsed is None
        if parsed is not None:
            targets.append(parsed)

    if url_name in MODEL_LOOKUPS:
        pk = kwargs.get('pk')
        if pk is None:
            invalid = True
        else:
            resolved = _lookup_makerspace_id(url_name, pk)
            invalid = invalid or resolved is None
            if resolved is not None:
                targets.append(resolved)

    target_set = set(targets)
    invalid = invalid or len(target_set) > 1
    return (
        url_name,
        target_set,
        invalid,
        route_recognized,
    )


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
