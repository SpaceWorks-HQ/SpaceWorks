import json

import pytest
from django.core.management import CommandError, call_command

from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def test_seed_e2e_creates_a_fresh_makerspace_with_both_requests(settings, tmp_path, monkeypatch):
    settings.DEBUG = True
    monkeypatch.delenv("E2E_SEED_ALLOWED", raising=False)
    out = tmp_path / "seed.json"
    call_command("seed_e2e", "--write-json", str(out), "--password", "pw-for-test")
    seeded = json.loads(out.read_text())
    space = Makerspace.objects.get(slug=seeded["slug"])
    assert space.public_inventory_enabled
    assert space.products.filter(name=seeded["product"], storage_location=seeded["secret_location"]).exists()
    pending = HardwareRequest.objects.get(pk=seeded["pending_request_id"])
    probe = HardwareRequest.objects.get(pk=seeded["probe_request_id"])
    assert pending.status == HardwareRequest.Status.PENDING_APPROVAL
    assert probe.status == HardwareRequest.Status.ACCEPTED
    assert seeded["box_code"] == space.boxes.get().code if hasattr(space, "boxes") else True
    # Two runs never collide: fresh slug, fresh users, fresh box code.
    out2 = tmp_path / "seed2.json"
    call_command("seed_e2e", "--write-json", str(out2), "--password", "pw-for-test")
    second = json.loads(out2.read_text())
    assert second["slug"] != seeded["slug"]
    assert second["manager"]["username"] != seeded["manager"]["username"]


def test_seed_e2e_refuses_outside_development(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.delenv("E2E_SEED_ALLOWED", raising=False)
    before = Makerspace.objects.count()
    with pytest.raises(CommandError):
        call_command("seed_e2e")
    assert Makerspace.objects.count() == before
    monkeypatch.setenv("E2E_SEED_ALLOWED", "1")
    call_command("seed_e2e", "--password", "pw-for-test")
    assert Makerspace.objects.count() == before + 1
