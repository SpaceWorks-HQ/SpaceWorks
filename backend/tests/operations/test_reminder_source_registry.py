import importlib
import sys

from apps.operations import reminder_registry
from apps.separability import registry


def test_core_registry_import_does_not_load_tombstoned_consumers(monkeypatch):
    monkeypatch.setattr(registry, "runtime_active", lambda label: False)
    monkeypatch.setitem(sys.modules, "apps.events.reminders", None)
    monkeypatch.setitem(sys.modules, "apps.bookings.reminders", None)
    monkeypatch.setitem(sys.modules, "apps.maintenance.reminders_meters", None)
    reloaded = importlib.reload(reminder_registry)
    assert {source.key for source in reloaded.registered_sources()} == {
        "membership.admission_payment", "membership.renewal", "payments.due", "loans.return", "loans.escalation",
        "inventory.back_available", "stocktake.scheduled", "notifications.deferred",
    }


def test_explicit_empty_override_does_not_load_any_production_consumer(monkeypatch):
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", ())
    monkeypatch.setitem(sys.modules, "apps.events.reminders", None)
    monkeypatch.setitem(sys.modules, "apps.bookings.reminders", None)
    assert reminder_registry.registered_sources() == ()
