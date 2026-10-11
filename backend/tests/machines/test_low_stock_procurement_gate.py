import pytest

from apps.audit.models import AuditLog
from apps.machines.low_stock import maybe_flag_low_stock
from apps.machines.models import MachineConsumablePool
from apps.procurement.models import ToBuyItem
from tests.modules.family_helpers import account, family_space

pytestmark = pytest.mark.django_db


def test_low_stock_never_creates_procurement_until_the_tenant_installs_it():
    space = family_space("low-stock-procurement-off", "machines")
    actor = account("low-stock-human", staff=True)
    pool = MachineConsumablePool.objects.create(makerspace=space, material="PLA", initial_grams="100",
        remaining_grams="5", low_threshold_grams="10", created_by=actor)
    assert maybe_flag_low_stock(actor, pool) is None
    assert not ToBuyItem.objects.filter(makerspace=space).exists()
    assert not AuditLog.objects.filter(makerspace=space, action="procurement.low_stock_flagged").exists()
    space.enabled_modules.append("procurement")
    space.save(update_fields=["enabled_modules"])
    first = maybe_flag_low_stock(actor, pool)
    assert first is not None
    assert maybe_flag_low_stock(actor, pool) is None
    assert ToBuyItem.objects.filter(source_pool=pool).count() == 1
    assert AuditLog.objects.get(makerspace=space, action="procurement.low_stock_flagged").actor == actor


def test_procurement_disable_between_guard_and_writer_is_rechecked(monkeypatch):
    from apps.machines import low_stock

    space = family_space("low-stock-disable-race", "machines", "procurement")
    actor = account("low-stock-race-actor", staff=True)
    pool = MachineConsumablePool.objects.create(makerspace=space, material="PLA", initial_grams="100",
        remaining_grams="5", low_threshold_grams="10", created_by=actor)

    def disable_after_unlocked_check(makerspace, key):
        assert key == "procurement"
        space.enabled_modules.remove("procurement")
        space.save(update_fields=["enabled_modules"])
        return True

    monkeypatch.setattr(low_stock, "module_enabled", disable_after_unlocked_check)
    assert maybe_flag_low_stock(actor, pool) is None
    assert not ToBuyItem.objects.filter(makerspace=space).exists()
    assert not AuditLog.objects.filter(makerspace=space, action="procurement.low_stock_flagged").exists()
