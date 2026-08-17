"""Export row-existence closure and typed inert snapshots."""

from collections import defaultdict

from django.apps import apps

from .datasets import DATASETS
from .types import Fidelity


def select_related_paths(model_label, row_rules):
    paths = {
        field_name
        for (label, field_name), _rule in row_rules.items()
        if label == model_label
    }
    for (label, _field), rule in row_rules.items():
        if label == model_label and rule.anchor_field:
            paths.add(rule.anchor_field)
    paths.update(
        {
            "operations.StockTransfer": {
                "makerspace",
                "source_makerspace",
                "destination_makerspace",
            },
            "operations.StockTransferLine": {
                "transfer__makerspace",
                "transfer__source_makerspace",
                "transfer__destination_makerspace",
                "product",
                "asset",
            },
            "operations.InventoryAdjustment": {
                "transfer__makerspace",
                "transfer__source_makerspace",
                "transfer__destination_makerspace",
            },
            "warranty.WarrantyDocument": {"warranty__asset"},
        }.get(model_label, set())
    )
    return paths


class ClosureReferenceProjector:
    """Classify references by archive row presence, not database existence."""

    def __init__(self, makerspace_id, write_record):
        from apps.tenant_migration.closure_references import (
            CROSS_TENANT_DEPENDENT_REFERENCES,
            MOVABLE_DISCRIMINATOR_REFERENCES,
            MOVABLE_LIST_REFERENCES,
            MOVABLE_ROW_REFERENCES,
            MissingReferenceDisposition,
        )

        self.makerspace_id = makerspace_id
        self.write_record = write_record
        self.row_rules = MOVABLE_ROW_REFERENCES
        self.list_rules = MOVABLE_LIST_REFERENCES
        self.discriminator_rules = MOVABLE_DISCRIMINATOR_REFERENCES
        self.dependent_rules = CROSS_TENANT_DEPENDENT_REFERENCES
        self.drop_disposition = MissingReferenceDisposition.DROP_WITH_PROVENANCE
        self.absent = {}
        self.non_live_ids = defaultdict(set)

    def prepare_rows(self, model_label, rows):
        plain = [item[0] if isinstance(item, tuple) else item for item in rows]
        self._prepare_direct(model_label, plain)
        self._prepare_lists(model_label, plain)
        self._prepare_discriminators(model_label, plain)
        self._prepare_dependents(model_label, plain)

    def project(self, row, field_name, value):
        key = (row._meta.label, str(row.pk), field_name)
        if key in self.absent:
            missing = self.absent[key]
            if isinstance(missing, set):
                return [item for item in (value or []) if int(item) not in missing]
            return None

        pair_key = (row._meta.label, str(row.pk), "target_type+target_id")
        if pair_key in self.absent:
            if field_name == "target_type":
                return f"external_{row.target_type}"
            if field_name == "target_id":
                return 0
        return value

    def _prepare_direct(self, model_label, rows):
        for edge, rule in self.row_rules.items():
            if edge[0] != model_label:
                continue
            ids = {
                getattr(row, row._meta.get_field(edge[1]).attname)
                for row in rows
                if getattr(row, row._meta.get_field(edge[1]).attname) is not None
            }
            present, targets = self._closure(rule.target_model_label, ids)
            for row in rows:
                value = getattr(row, row._meta.get_field(edge[1]).attname)
                if value is None or value in present:
                    continue
                self.absent[(model_label, str(row.pk), edge[1])] = True
                snapshot = self._reference(rule.target_model_label, value, targets)
                self._write(row, edge[1], snapshot, rule)

    def _prepare_lists(self, model_label, rows):
        for edge, rule in self.list_rules.items():
            if edge[0] != model_label:
                continue
            ids = {int(value) for row in rows for value in (getattr(row, edge[1]) or [])}
            present, targets = self._closure(rule.target_model_label, ids)
            for row in rows:
                missing = {int(value) for value in (getattr(row, edge[1]) or [])} - present
                if not missing:
                    continue
                self.absent[(model_label, str(row.pk), edge[1])] = missing
                snapshot = {
                    "references": [
                        self._reference(rule.target_model_label, value, targets)
                        for value in sorted(missing)
                    ]
                }
                self._write(row, edge[1], snapshot, rule)

    def _prepare_discriminators(self, model_label, rows):
        for edge, typed_rules in self.discriminator_rules.items():
            if edge[0] != model_label:
                continue
            for target_type, rule in typed_rules.items():
                selected = [row for row in rows if row.target_type == target_type]
                ids = {row.target_id for row in selected}
                present, targets = self._closure(rule.target_model_label, ids)
                for row in selected:
                    if row.target_id in present:
                        continue
                    field_name = "target_type+target_id"
                    self.absent[(model_label, str(row.pk), field_name)] = True
                    if rule.disposition is self.drop_disposition:
                        # Downstream edges must see the row's import disposition, not
                        # merely that its CSV row exists. Otherwise immutable scans can
                        # bind to a QR whose external target makes the QR itself inert.
                        self.non_live_ids[model_label].add(row.pk)
                    self._write(
                        row,
                        field_name,
                        self._reference(rule.target_model_label, row.target_id, targets),
                        rule,
                    )

    def _prepare_dependents(self, model_label, rows):
        if model_label == "operations.StockTransfer":
            for row in rows:
                if self._is_inbound(row):
                    self._write_synthetic(row, "inbound_transfer", self._transfer(row))
        elif model_label == "operations.StockTransferLine":
            for row in rows:
                if self._is_inbound(row.transfer):
                    self._write_synthetic(row, "inbound_transfer", self._transfer_line(row))
        elif model_label == "operations.InventoryAdjustment":
            for row in rows:
                if row.transfer_id and row.transfer.makerspace_id != self.makerspace_id:
                    self.absent[(model_label, str(row.pk), "transfer")] = True
                    self._write_synthetic(row, "transfer", self._transfer(row.transfer))
        elif model_label == "warranty.WarrantyDocument":
            for row in rows:
                warranty = row.warranty
                if warranty.asset_id and not self._is_in_closure(
                    "inventory.InventoryAsset", warranty.asset_id
                ):
                    self._write_synthetic(
                        row,
                        "external_warranty",
                        {
                            "source_id": row.pk,
                            "warranty_source_id": row.warranty_id,
                            "original_filename": row.original_filename,
                            "content_type": row.content_type,
                            "size_bytes": row.size_bytes,
                        },
                    )

    def _closure(self, target_label, ids):
        if not ids:
            return set(), {}
        model = apps.get_model(target_label)
        dataset = next(
            item
            for item in DATASETS.values()
            if item.fidelity is Fidelity.PORTABLE and item.model == target_label
        )
        present = set(
            model.objects.filter(
                dataset.predicate.as_q(self.makerspace_id), pk__in=ids
            ).values_list("pk", flat=True)
        )
        queryset = model.objects.filter(pk__in=ids)
        if target_label == "inventory.InventoryAsset":
            queryset = queryset.select_related("product")
        targets = {item.pk: item for item in queryset}

        # Viability is recursive for a row such as QrCode: the QR CSV row can be in
        # this tenant's predicate while its discriminator names an asset that moved
        # out. Treating that QR as present would leave scan history pointing at a row
        # whose own DROP_WITH_PROVENANCE disposition prevents it from importing.
        typed_rules = self.discriminator_rules.get(
            (target_label, "target_type", "target_id"), {}
        )
        for target_type, rule in typed_rules.items():
            typed = [item for item in targets.values() if item.target_type == target_type]
            viable, _details = self._closure(
                rule.target_model_label,
                {item.target_id for item in typed},
            )
            if rule.disposition is self.drop_disposition:
                self.non_live_ids[target_label].update(
                    item.pk for item in typed if item.target_id not in viable
                )
        present.difference_update(self.non_live_ids[target_label])
        return present, targets

    def _is_in_closure(self, target_label, target_id):
        return target_id in self._closure(target_label, {target_id})[0]

    @staticmethod
    def _reference(target_label, source_id, targets):
        target = targets.get(source_id)
        if target_label == "inventory.InventoryAsset" and target is not None:
            label = f"{target.product.name} / {target.asset_tag}"
        elif target_label == "boxes.QrCode" and target is not None:
            label = f"{target.target_type}:{target.target_id} [{target.status}]"
        else:
            label = ""
        return {
            "source_id": int(source_id),
            "target_model_label": target_label,
            "state": "external" if target is not None else "missing",
            "label": label,
        }

    def _write(self, row, field_name, snapshot, rule):
        anchor = getattr(row, rule.anchor_field) if rule.anchor_field else row
        self.write_record(row, field_name, snapshot, anchor=anchor)

    def _write_synthetic(self, row, field_name, snapshot):
        self.write_record(row, field_name, snapshot, anchor=row)

    def _is_inbound(self, transfer):
        return (
            transfer.destination_makerspace_id == self.makerspace_id
            and transfer.makerspace_id != self.makerspace_id
        )

    @staticmethod
    def _makerspace(value):
        return {"name": value.name, "slug": value.slug} if value else {"name": "", "slug": ""}

    def _transfer(self, transfer):
        return {
            "source_id": transfer.pk,
            "reason": transfer.reason,
            "status": transfer.status,
            "created_at": transfer.created_at.isoformat(),
            "owner": self._makerspace(transfer.makerspace),
            "source": self._makerspace(transfer.source_makerspace),
            "destination": self._makerspace(transfer.destination_makerspace),
        }

    @staticmethod
    def _transfer_line(row):
        return {
            "source_id": row.pk,
            "transfer_source_id": row.transfer_id,
            "product_name": row.product.name if row.product_id else "",
            "asset_label": row.asset.asset_tag if row.asset_id else "",
            "quantity": row.quantity,
            "from_status": row.from_status,
            "to_status": row.to_status,
            "notes": row.notes,
        }
