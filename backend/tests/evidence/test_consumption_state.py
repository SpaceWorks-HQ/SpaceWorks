"""Durable consumption proof: legacy-safe default, one-way SQL-guarded marker."""

import ast
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.db import Error, connection, transaction

from apps.accounts.models import User
from apps.evidence.consumption import mark_consumed
from apps.evidence.models import EvidencePhoto
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db
C = EvidencePhoto.ConsumptionState
APPS = Path(__file__).resolve().parents[2] / "apps"


def _photo(slug, state=None, key=None):
    space = Makerspace.objects.create(name=slug, slug=slug)
    user = get_user_model().objects.create_user(
        username=f"{slug}-u", email=f"{slug}@e.test", role=User.Role.SPACE_MANAGER
    )
    extra = {} if state is None else {"consumption_state": state}
    return EvidencePhoto.objects.create(
        makerspace=space,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=key or f"evidence/{slug}/k",
        uploaded_by=user,
        **extra,
    )


def _state(photo):
    return EvidencePhoto.objects.values_list("consumption_state", flat=True).get(pk=photo.pk)


def test_rows_default_to_legacy_unknown_in_python_and_in_postgres():
    photo = _photo("consume-default")
    assert _state(photo) == C.LEGACY_UNKNOWN
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO evidence_evidencephoto (makerspace_id, evidence_type, object_key,"
            " content_type, uploaded_by_id, created_at) VALUES (%s, 'issue', 'raw/k', '',"
            " %s, now()) RETURNING consumption_state",
            [photo.makerspace_id, photo.uploaded_by_id],
        )
        assert cursor.fetchone()[0] == C.LEGACY_UNKNOWN


@pytest.mark.parametrize("start", [C.LEGACY_UNKNOWN, C.UNCONSUMED])
def test_mark_consumed_is_one_way_and_idempotent(start):
    photo = _photo(f"consume-{start}", state=start)
    with transaction.atomic():
        assert mark_consumed(photo) is True
        assert mark_consumed(photo) is False
    assert _state(photo) == C.CONSUMED


def test_mark_consumed_rolls_back_with_its_domain_transaction():
    photo = _photo("consume-rollback", state=C.UNCONSUMED)
    with pytest.raises(RuntimeError, match="domain failure"):
        with transaction.atomic():
            mark_consumed(photo)
            raise RuntimeError("domain failure")
    assert _state(photo) == C.UNCONSUMED


def test_mark_consumed_refuses_to_run_outside_a_transaction(monkeypatch):
    photo = _photo("consume-no-txn", state=C.UNCONSUMED)
    # pytest-django wraps each test in a transaction; model "no atomic block".
    monkeypatch.setattr(connection, "in_atomic_block", False)
    with pytest.raises(RuntimeError, match="consuming transaction"):
        mark_consumed(photo)
    monkeypatch.undo()
    assert _state(photo) == C.UNCONSUMED


@pytest.mark.parametrize(
    "start, updates",
    [
        (C.CONSUMED, {"consumption_state": C.UNCONSUMED}),
        (C.CONSUMED, {"consumption_state": C.LEGACY_UNKNOWN}),
        (C.UNCONSUMED, {"consumption_state": C.LEGACY_UNKNOWN}),
        (C.UNCONSUMED, {"consumption_state": C.CONSUMED, "object_key": "evidence/other"}),
        (C.LEGACY_UNKNOWN, {"consumption_state": C.CONSUMED, "size_bytes": 9}),
        (C.CONSUMED, {"consumption_state": C.CONSUMED}),
        (C.UNCONSUMED, {"object_key": "evidence/moved"}),
    ],
)
def test_database_guard_rejects_every_other_update(start, updates):
    photo = _photo(f"consume-guard-{len(updates)}-{start}", state=start)
    with pytest.raises(Error):
        with transaction.atomic():
            EvidencePhoto.objects.filter(pk=photo.pk).update(**updates)
    assert _state(photo) == start


def test_database_guard_allows_the_bare_monotonic_transition():
    photo = _photo("consume-raw", state=C.UNCONSUMED)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE evidence_evidencephoto SET consumption_state='consumed' WHERE id=%s",
            [photo.pk],
        )
    assert _state(photo) == C.CONSUMED


CONSUMERS = {
    "hardware_requests/handover_workflow.py": ("issue_request",),
    "hardware_requests/return_workflow.py": ("return_items",),
    "hardware_requests/direct_loan_workflow.py": ("issue_direct_loan",),
    "hardware_requests/direct_loan_returns.py": ("return_direct_loan",),
    # self_checkout_workflow.py is a re-export barrel over these two since the 9b split.
    "hardware_requests/self_checkout_issue.py": ("checkout_tool",),
    "hardware_requests/self_checkout_returns.py": ("return_tool",),
    "hardware_requests/problem_report_workflow.py": ("triage_problem_report",),
}


def _atomic_blocks(function):
    for node in ast.walk(function):
        if isinstance(node, ast.With) and any(
            "atomic" in ast.unparse(item.context_expr) for item in node.items
        ):
            yield node


@pytest.mark.parametrize("path, names", CONSUMERS.items())
def test_all_seven_consumers_mark_inside_their_attachment_transaction(path, names):
    tree = ast.parse((APPS / path).read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    for name in names:
        function = functions[name]
        calls = [
            ast.unparse(call.func)
            for block in _atomic_blocks(function)
            for call in ast.walk(block)
            if isinstance(call, ast.Call)
        ]
        assert "charge_storage_once" in calls, name
        assert "mark_consumed" in calls, name


def _creates_unconsumed(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call)
        # The staff presign reaches the row through the shared issue_upload service,
        # whose own default is legacy_unknown; only the caller's opt-in counts.
        and (getattr(node.func, "attr", None) or getattr(node.func, "id", None))
        in {"create", "issue_upload"}
        and any(
            item.arg == "consumption_state" and "UNCONSUMED" in ast.unparse(item.value)
            for item in node.keywords
        )
        for node in ast.walk(tree)
    )


def test_only_the_two_presign_views_create_unconsumed_rows():
    hits = sorted(
        str(path.relative_to(APPS)).replace("\\", "/")
        for path in APPS.rglob("*.py")
        if "migrations" not in path.parts and _creates_unconsumed(path)
    )
    assert hits == ["evidence/views.py", "hardware_requests/self_checkout_views.py"]
