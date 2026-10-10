"""A preference may disappear; its audit history must remain portable evidence."""
import json

import pytest

from apps.audit import services as audit
from apps.operations.models import SavedView
from apps.tenant_migration.row_planning import _apply_target_fields
from tests.data_export.portable_helpers import archive_files, csv_rows, make_job, make_space, make_user

pytestmark = pytest.mark.django_db(transaction=True)


def test_deleted_and_live_saved_views_keep_inert_audit_targets_in_portable_export():
    space = make_space("saved-portable")
    owner = make_user("saved-portable-owner")
    live = SavedView.objects.create(makerspace=space, owner=owner, name="Live", entity="inventory")
    removed = SavedView.objects.create(makerspace=space, owner=owner, name="Gone", entity="inventory")
    logs = [audit.record(owner, "saved_view.created", makerspace=space, target=live),
            audit.record(owner, "saved_view.deleted", makerspace=space, target=removed)]
    removed_id = removed.pk
    removed.delete()

    files, _bytes, _manifest = archive_files(make_job(space, owner))
    preferences = csv_rows(files, "preferences/saved_views.csv")
    assert [row["id"] for row in preferences] == [str(live.pk)]
    rows = {row["id"]: row for row in csv_rows(files, "audit/audit_log.csv")}
    records = [json.loads(line) for line in files["migration/reference_provenance.jsonl"].splitlines()]
    for log, source_id in zip(logs, (live.pk, removed_id)):
        assert (rows[str(log.pk)]["target_type"], rows[str(log.pk)]["target_id"]) == ("", "")
        reference = next(record for record in records if record["source_object_id"] == str(log.pk)
                         and record["field_name"] == "target_type+target_id")
        assert reference["kind"] == "audit_saved_view_target"
        assert reference["detail"]["source_target_id"] == str(source_id)


def test_import_planner_resets_publication_and_source_filters_on_saved_view_rows():
    source = {"id": "7", "shared": "true", "state": '{"actor":"123", "q":"drill"}'}
    planned = {"id": 9, "shared": True, "state": {"actor": "123", "q": "drill"}}
    _apply_target_fields("operations.SavedView", source, planned)
    assert planned == {"id": 9, "shared": False, "state": {}}
