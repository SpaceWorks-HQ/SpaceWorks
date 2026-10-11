"""Checklist snapshots add to the existing evidence-backed loan transaction."""

from collections import Counter
from uuid import UUID, uuid5

from apps.audit import services as audit
from apps.hardware_requests.models import RequesterAccountability
from apps.hardware_requests.workflow_errors import RequestValidationError
from apps.makerspaces.platform import feature_enabled


def expectations(components, owner_label, units=1):
    return [
        {"key": row["key"], "label": row["label"], "owner_label": owner_label,
         "per_unit": row["quantity"], "quantity": row["quantity"] * units}
        for row in components
    ]


def issue_expectations(request, box=None, rejects=None, *, issued=False):
    if not feature_enabled(request.makerspace, "loans.kit_checklist"):
        return []
    return [row for _owner, rows in _issue_groups(request, box, rejects, issued=issued) for row in rows]


def unique_expectations(groups):
    """Disambiguate copied definitions using opaque keys, with no stored model IDs."""
    frequencies = Counter(row["key"] for _owner, rows in groups for row in rows)
    for owner, rows in groups:
        for row in rows:
            if frequencies[row["key"]] > 1:
                row["key"] = str(uuid5(UUID(row["key"]), owner))
    return groups


def _issue_groups(request, box, rejects=None, *, issued=False):
    rejected = {entry["item_id"]: entry.get("broken", 0) for entry in (rejects or [])}
    items = list(request.items.select_related("product").order_by("pk"))
    frequencies = Counter(item.product_id for item in items)
    groups = []
    for item in items:
        units = item.issued_quantity if issued else item.accepted_quantity - rejected.get(item.pk, 0)
        if units > 0:
            owner = f"product:{item.product_id}"
            if frequencies[item.product_id] > 1:
                owner += f":item:{item.pk}"
            groups.append((owner, expectations(item.product.kit_components, item.product.name, units)))
    if box:
        groups.append((f"box:{box.pk}", expectations(box.kit_components, box.label)))
    return unique_expectations(groups)


def _counted(expected, counts):
    counts = list(counts or [])
    keys = [str(row.get("key", "")) for row in counts]
    expected_keys = [row["key"] for row in expected]
    if len(expected_keys) != len(set(expected_keys)):
        raise RequestValidationError("Kit component keys must be unique across this loan.")
    if len(keys) != len(set(keys)) or set(keys) != set(expected_keys):
        raise RequestValidationError("Record every required kit component exactly once.")
    values = {str(row["key"]): row["present"] for row in counts}
    result = []
    for row in expected:
        if row["quantity"] > 2147483647:
            raise RequestValidationError("Kit component quantity exceeds the supported count limit.")
        present = values[row["key"]]
        if type(present) is not int or not 0 <= present <= row["quantity"]:
            raise RequestValidationError("Component present count must be within the expected quantity.")
        result.append({**row, "present": present})
    return result


def record_issue(actor, request, box, counts):
    groups = _issue_groups(request, box, issued=True) if feature_enabled(request.makerspace, "loans.kit_checklist") else []
    rows = _counted([row for _owner, group in groups for row in group], counts)
    by_key = {row["key"]: row for row in rows}
    by_owner = {owner: [by_key[expected["key"]] for expected in group]
                for owner, group in groups}
    if rows:
        items = list(request.items.all())
        frequencies = Counter(item.product_id for item in items)
        for item in items:
            owner = f"product:{item.product_id}"
            if frequencies[item.product_id] > 1:
                owner += f":item:{item.pk}"
            item.issue_checklist = by_owner.get(owner, [])
            item.save(update_fields=["issue_checklist"])
        request.box_issue_checklist = by_owner.get(f"box:{box.pk}", []) if box else []
        request.save(update_fields=["box_issue_checklist", "updated_at"])
        audit.record(actor, "kit.issue_recorded", makerspace=request.makerspace, target=request)
    return rows


def return_expectations(request, resolutions):
    """Partition issued component counts across partial returns without double blame."""
    previously_checked = {}
    for event in request.returnevent_set.all():
        for row in event.kit_checklist:
            previously_checked[row["key"]] = previously_checked.get(row["key"], 0) + row["baseline"]
    units = {
        row["item"].pk: row["returned"] + row["damaged"] + row["missing"]
        for row in resolutions
    }
    rows = []
    all_resolved = True
    for item in request.items.all():
        outstanding = item.issued_quantity - item.returned_quantity - item.damaged_quantity - item.missing_quantity
        count = units.get(item.pk, 0)
        all_resolved = all_resolved and count == outstanding
        if count > 0:
            for row in item.issue_checklist:
                expected = row["per_unit"] * count
                baseline = min(expected, max(0, row["present"] - previously_checked.get(row["key"], 0)))
                rows.append({**row, "quantity": expected, "baseline": baseline, "issue_present": row["present"]})
    if all_resolved:
        rows.extend({**row, "baseline": row["present"], "issue_present": row["present"]}
                    for row in request.box_issue_checklist)
    return rows


def record_return(actor, request, evidence, resolutions, counts):
    rows = _counted(return_expectations(request, resolutions), counts)
    item_for_key = {row["key"]: item for item in request.items.all() for row in item.issue_checklist}
    for row in rows:
        missing = max(0, row["baseline"] - row["present"])
        if not missing:
            continue
        item = item_for_key.get(row["key"])
        RequesterAccountability.objects.create(
            requester=request.requester, request=request, request_item=item,
            makerspace=request.makerspace, issue_type=RequesterAccountability.IssueType.MISSING,
            description=f"Kit {row['owner_label']}: {row['label']} — {missing} component(s) missing.",
            evidence_photo=evidence, quantity=missing, created_by=actor,
        )
        audit.record(actor, "kit.component_missing", makerspace=request.makerspace, target=request)
    if rows:
        audit.record(actor, "kit.return_recorded", makerspace=request.makerspace, target=request)
    return rows


def checklist_remark(remark, rows):
    if not rows:
        return remark
    rendered = "; ".join(f"{row['owner_label']} / {row['label']}: {row['present']}/{row['quantity']} present" for row in rows)
    return f"{remark}\nKit checklist: {rendered}".strip()
