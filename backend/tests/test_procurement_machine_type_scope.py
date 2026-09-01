import pytest

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct
from apps.machines.models import (
    Machine,
    MachineConsumablePool,
    MachineType,
    RoleMachineScope,
    RoleMachineTypeScope,
)
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from tests.return_helpers import authenticated_client, make_member, make_space, make_user
from tests.test_procurement import make_space_manager, make_superadmin

pytestmark = pytest.mark.django_db


def list_url(space):
    return f"/api/v1/procurement/makerspace/{space.pk}/to-buy"


def detail_url(item):
    return f"/api/v1/procurement/to-buy/{item.pk}"


def options_for(actor, space, kind="printing"):
    response = authenticated_client(actor).get(option_url(space, kind))
    assert response.status_code == 200
    return {row["id"] for row in response.data["results"]}


def requires_type(actor, space, kind="printing"):
    return authenticated_client(actor).get(option_url(space, kind)).data[
        "machine_type_required"
    ]


def option_url(space, kind="printing"):
    return f"{list_url(space)}/machine-types?kind={kind}"


def scoped_manager(space, username, *, types=(), machine=None, actions=None):
    actor = make_user(username, access_status=User.AccessStatus.ACTIVE)
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name=username,
        slug=username,
        granted_actions=actions or [Action.MANAGE_MACHINES],
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    for machine_type in types:
        RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
    if machine is not None:
        RoleMachineScope.objects.create(role=role, machine=machine)
    return actor


def type_for(space, slug):
    return MachineType.objects.create(makerspace=space, slug=slug, name=slug.title())


def printing_item(space, name, machine_type=None, **overrides):
    return ToBuyItem.objects.create(
        makerspace=space,
        kind=ToBuyItem.Kind.PRINTING,
        machine_type=machine_type,
        name=name,
        **overrides,
    )


def listed_names(actor, space):
    response = authenticated_client(actor).get(list_url(space))
    assert response.status_code == 200
    return {row["name"] for row in response.data}


def test_assigned_role_type_scope_matrix_and_null_fail_closed():
    space = make_space("proc-type-matrix")
    lasers = type_for(space, "matrix-lasers")
    printers = type_for(space, "matrix-printers")
    laser_machine = Machine.objects.create(
        makerspace=space, machine_type=lasers, name="Only linked machine"
    )
    printing_item(space, "Laser stock", lasers)
    printing_item(space, "Printer stock", printers)
    printing_item(space, "Legacy unassigned")

    none = scoped_manager(space, "proc-scope-none")
    one = scoped_manager(space, "proc-scope-one", types=[lasers])
    both = scoped_manager(space, "proc-scope-both", types=[lasers, printers])
    machine_only = scoped_manager(
        space, "proc-scope-machine-only", machine=laser_machine
    )

    assert listed_names(none, space) == set()
    assert listed_names(one, space) == {"Laser stock"}
    assert listed_names(both, space) == {"Laser stock", "Printer stock"}
    assert listed_names(machine_only, space) == set()
    assert options_for(none, space) == set()
    assert options_for(one, space) == {lasers.pk}
    assert options_for(both, space) == {lasers.pk, printers.pk}
    assert options_for(machine_only, space) == set()
    # Every one of these is scope-restricted, so the server must SAY a type is required --
    # including the two that can reach no type at all, where the console shows the
    # "no machine types are linked to your role" hint rather than a silently optional field.
    for actor in (none, one, both, machine_only):
        assert requires_type(actor, space) is True


def test_exempt_actors_keep_null_and_all_typed_rows_visible():
    space = make_space("proc-type-exempt")
    lasers = type_for(space, "exempt-lasers")
    printing_item(space, "Typed", lasers)
    printing_item(space, "Unassigned")
    legacy = make_member(
        "proc-exempt-legacy",
        space,
        membership_role=MakerspaceMembership.Role.MACHINE_MANAGER,
        role=User.Role.REQUESTER,
    )
    actors = [
        make_space_manager("proc-exempt-space-manager", space),
        make_superadmin("proc-exempt-superadmin"),
        legacy,
    ]

    for actor in actors:
        assert listed_names(actor, space) == {"Typed", "Unassigned"}
        options = authenticated_client(actor).get(option_url(space))
        assert options.status_code == 200
        assert lasers.pk in {row["id"] for row in options.data["results"]}
        # Exempt actors may leave it Unassigned.
        assert options.data["machine_type_required"] is False


def test_hardware_stream_is_unchanged_for_assigned_machine_role():
    space = make_space("proc-type-hardware")
    actor = scoped_manager(
        space,
        "proc-type-hardware-actor",
        actions=[Action.MANAGE_MACHINES, Action.EDIT_INVENTORY],
    )
    item = ToBuyItem.objects.create(
        makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Unassigned hardware"
    )

    assert listed_names(actor, space) == {item.name}
    created = authenticated_client(actor).post(
        list_url(space), {"name": "New hardware", "quantity": 1}, format="json"
    )
    assert created.status_code == 201
    assert created.data["machine_type"] is None


def test_actor_without_manage_machines_keeps_broad_type_options():
    space = make_space("proc-type-direct-print")
    first = type_for(space, "direct-first")
    second = type_for(space, "direct-second")
    actor = scoped_manager(
        space,
        "proc-type-direct-print-actor",
        actions=[Action.MANAGE_PRINTING],
    )

    response = authenticated_client(actor).get(option_url(space))

    assert response.status_code == 200
    assert {row["id"] for row in response.data["results"]} >= {first.pk, second.pk}
    # No MANAGE_MACHINES at all means no machine-scope narrowing, so nothing is required.
    assert response.data["machine_type_required"] is False


def test_a_directly_granted_printing_role_keeps_the_whole_stream():
    """The leak is the IMPLIED printing grant, not a stored one.

    `IMPLIED_ACTIONS[MANAGE_MACHINES]` contains `MANAGE_PRINTING`, which is how a
    laser-scoped role silently inherited every printing row. But a role whose
    `granted_actions` really lists `manage_printing` was handed that stream deliberately,
    and narrowing it because the role also gained machine duties revokes an independent
    grant -- the mixed-role mistake from the dashboard, in a second place.
    """
    space = make_space("proc-type-direct-both")
    mine = type_for(space, "direct-both-mine")
    theirs = type_for(space, "direct-both-theirs")
    printing_item(space, "Mine", mine)
    printing_item(space, "Theirs", theirs)
    printing_item(space, "Unassigned", None)

    implied = scoped_manager(space, "proc-both-implied", types=[mine])
    stored = scoped_manager(
        space,
        "proc-both-stored",
        types=[mine],
        actions=[Action.MANAGE_MACHINES, Action.MANAGE_PRINTING],
    )

    # Implied-only: narrowed, and the unassigned legacy row stays hidden.
    assert listed_names(implied, space) == {"Mine"}
    assert requires_type(implied, space) is True
    # Stored grant: the whole stream, including legacy NULL rows, and no forced type.
    assert listed_names(stored, space) == {"Mine", "Theirs", "Unassigned"}
    assert requires_type(stored, space) is False


def test_the_type_cannot_be_retagged_away_from_durable_provenance():
    """The label is an authorization boundary, so it must keep describing the asset.

    An exempt manager is trusted, so this is integrity rather than escalation: retagging a
    row that came from a real machine hides it from the team owning that machine and shows
    it to another, while contradicting the machine it names.
    """
    space = make_space("proc-type-retag")
    owning = type_for(space, "retag-owning")
    other = type_for(space, "retag-other")
    machine = Machine.objects.create(
        makerspace=space, machine_type=owning, name="Owning machine"
    )
    item = printing_item(space, "Moved", owning)
    item.resulting_machine = machine
    item.save(update_fields=["resulting_machine"])

    manager = make_space_manager("proc-retag-manager", space)
    client = authenticated_client(manager)
    url = detail_url(item)

    retag = client.patch(url, {"machine_type": other.pk}, format="json")
    cleared = client.patch(url, {"machine_type": None}, format="json")
    unchanged = client.patch(url, {"machine_type": owning.pk}, format="json")

    assert retag.status_code == 400 and "machine_type" in retag.data
    assert cleared.status_code == 400 and "machine_type" in cleared.data
    # Re-asserting what provenance already implies is a no-op, so nothing is trapped.
    assert unchanged.status_code == 200
    item.refresh_from_db()
    assert item.machine_type == owning

    # A row with no provenance stays freely taggable.
    free = printing_item(space, "Free", owning)
    assert client.patch(
        detail_url(free), {"machine_type": other.pk}, format="json"
    ).status_code == 200


def test_restricted_creation_requires_a_reachable_local_or_global_type():
    space = make_space("proc-type-create")
    other = make_space("proc-type-create-other")
    reachable = type_for(space, "create-reachable")
    hidden = type_for(space, "create-hidden")
    foreign = type_for(other, "create-foreign")
    actor = scoped_manager(space, "proc-type-create-actor", types=[reachable])
    client = authenticated_client(actor)

    missing = client.post(list_url(space), {"name": "Missing"}, format="json")
    unreachable = client.post(
        list_url(space), {"name": "Hidden", "machine_type": hidden.pk}, format="json"
    )
    cross_tenant = client.post(
        list_url(space), {"name": "Foreign", "machine_type": foreign.pk}, format="json"
    )
    accepted = client.post(
        list_url(space), {"name": "Reachable", "machine_type": reachable.pk}, format="json"
    )

    assert missing.status_code == 400 and "machine_type" in missing.data
    assert unreachable.status_code == 400 and "machine_type" in unreachable.data
    assert cross_tenant.status_code == 400 and "machine_type" in cross_tenant.data
    assert accepted.status_code == 201
    assert ToBuyItem.objects.get(pk=accepted.data["id"]).machine_type == reachable
    assert not ToBuyItem.objects.filter(name__in=["Missing", "Hidden", "Foreign"]).exists()


def test_list_detail_and_export_hide_another_type():
    space = make_space("proc-type-read-surfaces")
    allowed_type = type_for(space, "read-allowed")
    hidden_type = type_for(space, "read-hidden")
    allowed = printing_item(space, "Allowed row", allowed_type)
    hidden = printing_item(space, "Hidden row", hidden_type)
    actor = scoped_manager(space, "proc-type-read-actor", types=[allowed_type])
    client = authenticated_client(actor)

    assert listed_names(actor, space) == {allowed.name}
    assert client.get(detail_url(allowed)).status_code == 200
    assert client.get(detail_url(hidden)).status_code == 404
    retyped = client.patch(
        detail_url(allowed), {"machine_type": hidden_type.pk}, format="json"
    )
    allowed.refresh_from_db()
    assert retyped.status_code == 400
    assert allowed.machine_type == allowed_type
    exported = client.get(f"{list_url(space)}/export")
    assert exported.status_code == 200
    assert "Allowed row" in exported.content.decode()
    assert "Hidden row" not in exported.content.decode()


@pytest.mark.parametrize(
    ("method", "path_kind", "payload"),
    [
        ("patch", "detail", {"status": "cancelled"}),
        ("delete", "detail", None),
        ("post", "presign", {"filename": "receipt.pdf", "content_type": "application/pdf"}),
        ("get", "receipt-list", None),
        ("post", "receipt-list", {"object_key": "procurement/1/receipt.pdf"}),
        ("get", "receipt-url", None),
        ("delete", "receipt-detail", None),
        ("post", "move-inventory", {"mode": "create", "quantity": 1, "name": "Nope"}),
        ("post", "move-printing", {"target": "printer", "name": "Nope", "model": "Nope"}),
    ],
)
def test_mutating_and_receipt_surfaces_refuse_another_type_without_changes(
    method, path_kind, payload
):
    space = make_space(f"proc-type-surface-{method}-{path_kind}")
    allowed_type = type_for(space, f"allowed-{method}-{path_kind}")
    hidden_type = type_for(space, f"hidden-{method}-{path_kind}")
    actor = scoped_manager(
        space, f"actor-{method}-{path_kind}", types=[allowed_type]
    )
    hidden = printing_item(
        space,
        "Protected row",
        hidden_type,
        status=ToBuyItem.Status.RECEIVED,
    )
    receipt = ToBuyReceipt.objects.create(
        to_buy_item=hidden,
        object_key=f"procurement/{space.pk}/protected.pdf",
    )
    paths = {
        "detail": detail_url(hidden),
        "presign": f"{detail_url(hidden)}/receipts/presign",
        "receipt-list": f"{detail_url(hidden)}/receipts",
        "receipt-url": f"/api/v1/procurement/to-buy/receipts/{receipt.pk}/url",
        "receipt-detail": f"/api/v1/procurement/to-buy/receipts/{receipt.pk}",
        "move-inventory": f"{detail_url(hidden)}/move-to-inventory",
        "move-printing": f"{detail_url(hidden)}/move-to-printing",
    }
    before_audits = AuditLog.objects.count()
    before_products = InventoryProduct.objects.count()
    before_machines = Machine.objects.count()
    before_pools = MachineConsumablePool.objects.count()

    response = getattr(authenticated_client(actor), method)(
        paths[path_kind], data=payload, format="json"
    )

    hidden.refresh_from_db()
    assert response.status_code == 404
    assert hidden.status == ToBuyItem.Status.RECEIVED
    assert hidden.moved_to_inventory_at is None
    assert ToBuyItem.objects.filter(pk=hidden.pk).exists()
    assert ToBuyReceipt.objects.filter(pk=receipt.pk).exists()
    assert AuditLog.objects.count() == before_audits
    assert InventoryProduct.objects.count() == before_products
    assert Machine.objects.count() == before_machines
    assert MachineConsumablePool.objects.count() == before_pools
