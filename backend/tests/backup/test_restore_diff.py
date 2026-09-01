from contextlib import AbstractContextManager
from datetime import datetime, timezone

from apps.backup import restore_diff


class SnapshotCursor(AbstractContextManager):
    def __init__(self, events):
        self.events = events

    def execute(self, sql):
        self.events.append(("sql", sql))

    def fetchone(self):
        return (datetime(2026, 8, 16, tzinfo=timezone.utc),)

    def __exit__(self, *_args):
        return False


class Introspection:
    def __init__(self, tables):
        self.tables = tables

    def table_names(self):
        return self.tables


class Connection:
    def __init__(self, tables, events):
        self.introspection = Introspection(tables)
        self.events = events

    def cursor(self):
        return SnapshotCursor(self.events)


def test_every_table_and_operator_decision_share_one_read_only_snapshot(monkeypatch):
    events = []
    transaction_open = {"value": False}

    class Atomic(AbstractContextManager):
        def __enter__(self):
            assert not transaction_open["value"]
            transaction_open["value"] = True
            events.append(("transaction", "open"))

        def __exit__(self, *_args):
            events.append(("transaction", "close"))
            transaction_open["value"] = False

    live = Connection(["live_only", "shared"], events)
    archive = Connection(["archive_only", "shared"], events)
    monkeypatch.setattr(restore_diff, "connections", {"live": live, "archive": archive})
    monkeypatch.setattr(restore_diff.transaction, "atomic", lambda using: Atomic())
    compared = []

    def compare(_live, _archive, table, *_args):
        assert transaction_open["value"]
        compared.append(table)
        return {"table": table, "changed": table != "shared"}

    monkeypatch.setattr(restore_diff, "_compare_table", compare)

    def decision(report):
        assert transaction_open["value"]
        events.append(("decision", report["tables_compared"]))

    report = restore_diff.compute_restore_diff(
        archive_using="archive", live_using="live", within_snapshot=decision
    )

    assert compared == ["archive_only", "live_only", "shared"]
    assert report["tables_compared"] == 3
    assert report["tables_changed"] == 2
    assert any("REPEATABLE READ, READ ONLY" in sql for kind, sql in events if kind == "sql")
    assert events.index(("decision", 3)) < events.index(("transaction", "close"))


def test_row_descent_runs_only_for_a_table_whose_summary_differs(monkeypatch):
    live, archive = object(), object()
    summaries = {
        (live, "same"): {"row_count": 1, "content_hash": "x"},
        (archive, "same"): {"row_count": 1, "content_hash": "x"},
        (live, "changed"): {"row_count": 1, "content_hash": "x"},
        (archive, "changed"): {"row_count": 2, "content_hash": "y"},
    }
    monkeypatch.setattr(restore_diff, "_table_summary", lambda connection, table: summaries[(connection, table)])
    descended = []
    monkeypatch.setattr(
        restore_diff,
        "_row_descent",
        lambda *_args: descended.append(_args[2]) or {"identity": ["id"]},
    )

    tables = {"same", "changed"}
    restore_diff._compare_table(live, archive, "same", tables, tables, 10)
    restore_diff._compare_table(live, archive, "changed", tables, tables, 10)

    assert descended == ["changed"]
