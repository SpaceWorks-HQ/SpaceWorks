from django.db.models import Count, Max, Sum

from apps.boxes.models import Box, QrCode
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.platform import module_enabled
from apps.operations.models import QrPrintBatch, StockTransfer, StocktakeSession
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import limited, report_spaces


FIELDS = (
    "module_key", "metric_key", "dimension", "count", "quantity",
    "rate_percent", "last_activity_at",
)


def build_inventory_control(makerspace_id, *, limit=None, date_range=None):
    aggregate = makerspace_id is None
    records = []
    for space in report_spaces(makerspace_id):
        add = lambda **values: _add(records, space.id, aggregate, **values)
        if module_enabled(space, "public_inventory"):
            _products(space.id, add)
        if module_enabled(space, "qr_management"):
            _grouped(QrCode.objects.filter(makerspace=space), "qr_management", "qr_status", "status", add)
        if module_enabled(space, "containers"):
            _containers(space.id, add)
        if module_enabled(space, "stock_transfers"):
            _transfers(space.id, add)
        if module_enabled(space, "stocktake"):
            _stocktakes(space.id, add)
        if module_enabled(space, "qr_print_batches"):
            _qr_batches(space.id, add)
        if module_enabled(space, "asset_units"):
            _grouped(InventoryAsset.objects.filter(makerspace=space), "asset_units", "asset_status", "status", add)
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit))


def _products(space_id, add):
    qs = InventoryProduct.objects.filter(makerspace_id=space_id, is_archived=False)
    total = qs.count()
    public = qs.filter(is_public=True).count()
    add(module_key="public_inventory", metric_key="visibility", dimension="public", count=public,
        rate_percent=round(public / total * 100, 2) if total else None, last_activity_at=_latest(qs))
    for row in qs.values("public_availability_mode").annotate(count=Count("id")):
        add(module_key="public_inventory", metric_key="availability_mode",
            dimension=row["public_availability_mode"], count=row["count"])


def _containers(space_id, add):
    qs = Box.objects.filter(makerspace_id=space_id)
    totals = qs.aggregate(count=Count("id"), active=Count("id", filter=models_q(is_active=True)), last=Max("updated_at"))
    assigned = InventoryProduct.objects.filter(makerspace_id=space_id, box__isnull=False).count()
    assigned += InventoryAsset.objects.filter(makerspace_id=space_id, box__isnull=False).count()
    add(module_key="containers", metric_key="containers", dimension="all", count=totals["count"],
        quantity=assigned, rate_percent=round(totals["active"] / totals["count"] * 100, 2) if totals["count"] else None,
        last_activity_at=totals["last"])


def _transfers(space_id, add):
    qs = StockTransfer.objects.filter(makerspace_id=space_id)
    for row in qs.values("status").annotate(count=Count("id", distinct=True), quantity=Sum("lines__quantity"), last=Max("created_at")):
        add(module_key="stock_transfers", metric_key="transfer_status", dimension=row["status"],
            count=row["count"], quantity=row["quantity"] or 0, last_activity_at=row["last"])


def _stocktakes(space_id, add):
    qs = StocktakeSession.objects.filter(makerspace_id=space_id)
    for row in qs.values("status").annotate(count=Count("id", distinct=True), quantity=Sum("lines__variance_quantity"), last=Max("started_at")):
        add(module_key="stocktake", metric_key="session_status", dimension=row["status"],
            count=row["count"], quantity=row["quantity"] or 0, last_activity_at=row["last"])


def _qr_batches(space_id, add):
    qs = QrPrintBatch.objects.filter(makerspace_id=space_id)
    for row in qs.values("status").annotate(count=Count("id", distinct=True), quantity=Count("items"), last=Max("created_at")):
        add(module_key="qr_print_batches", metric_key="batch_status", dimension=row["status"],
            count=row["count"], quantity=row["quantity"], last_activity_at=row["last"])


def _grouped(qs, module_key, metric_key, field, add):
    for row in qs.values(field).annotate(count=Count("id"), last=Max("updated_at")):
        add(module_key=module_key, metric_key=metric_key, dimension=row[field],
            count=row["count"], last_activity_at=row["last"])


def _latest(qs):
    return qs.aggregate(value=Max("updated_at"))["value"]


def _add(records, space_id, aggregate, **values):
    row = {field: values.get(field) for field in FIELDS}
    if aggregate:
        row["makerspace_id"] = space_id
    records.append(row)


def models_q(**kwargs):
    from django.db.models import Q
    return Q(**kwargs)
