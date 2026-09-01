import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    ServiceBucket,
    ServiceRequestFile,
)
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.organizations.test_org_authority import (
    grant,
    link,
    make_makerspace,
    make_organization,
    make_user,
)


pytestmark = pytest.mark.django_db


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def _org_collector(slug, makerspace):
    actor = make_user(f"{slug}-collector")
    organization = make_organization(f"{slug}-org")
    link(organization, makerspace, "manager")
    grant(organization, actor, [rbac.Action.COLLECT_SERVICE_REQUEST])
    return actor


def _local_without_actions(slug, makerspace):
    actor = make_user(f"{slug}-local")
    role = MakerspaceRole.objects.create(
        makerspace=makerspace, name=slug, slug=slug, granted_actions=[]
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return actor


def _machine(makerspace, slug):
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug=f"{slug}-type", name=f"{slug} type"
    )
    return Machine.objects.create(
        makerspace=makerspace, machine_type=machine_type, name=slug
    )


def _request(makerspace, machine, requester, status, slug):
    bucket, _created = ServiceBucket.objects.get_or_create(
        machine=machine, name="Organization service"
    )
    return MachineServiceRequest.objects.create(
        makerspace=makerspace,
        bucket=bucket,
        assigned_machine=machine,
        requester=requester,
        title=slug,
        status=status,
    )


def _list_url(makerspace):
    return reverse(
        "admin-machine-service-request-list-create", args=[makerspace.pk]
    )


def _detail_url(row):
    return reverse("admin-machine-service-request-detail", args=[row.pk])


def _action_url(row, action):
    return reverse(f"admin-machine-service-request-{action}", args=[row.pk])


def test_org_direct_collection_is_completed_only_and_cannot_mutate_lifecycle():
    makerspace = make_makerspace("org-service")
    foreign_space = make_makerspace("org-service-foreign")
    actor = _org_collector("org-service", makerspace)
    requester = make_user("org-service-requester")
    machine = _machine(makerspace, "org-service-machine")
    foreign_machine = _machine(foreign_space, "org-service-foreign-machine")
    completed = _request(
        makerspace, machine, requester, MachineServiceRequest.Status.COMPLETED, "done"
    )
    pending = _request(
        makerspace, machine, requester, MachineServiceRequest.Status.PENDING, "pending"
    )
    in_progress = _request(
        makerspace,
        machine,
        requester,
        MachineServiceRequest.Status.IN_PROGRESS,
        "running",
    )
    foreign = _request(
        foreign_space,
        foreign_machine,
        requester,
        MachineServiceRequest.Status.COMPLETED,
        "foreign",
    )
    attached = ServiceRequestFile.objects.create(
        service_request=completed,
        makerspace=makerspace,
        machine=machine,
        kind=ServiceRequestFile.Kind.ATTACHMENT,
        object_key="organization/service/attached.pdf",
        owner_user_id=requester.pk,
        attached_at=timezone.now(),
    )
    client = _client(actor)

    listed = client.get(_list_url(makerspace))
    assert listed.status_code == 200
    assert {row["id"] for row in listed.data} == {completed.id}
    assert client.get(_detail_url(completed)).status_code == 200
    for hidden in (pending, in_progress, foreign):
        assert client.get(_detail_url(hidden)).status_code == 404
    for action in ("accept", "reject", "start", "complete", "fail", "reprint"):
        assert client.post(_action_url(completed, action), {}, format="json").status_code == 404
    assert client.post(
        reverse("admin-machine-service-file-presign", args=[completed.pk]),
        {},
        format="json",
    ).status_code == 404
    assert client.post(
        reverse("admin-machine-service-file-finalize", args=[completed.pk]),
        {},
        format="json",
    ).status_code == 404
    assert client.get(
        reverse("admin-machine-service-file-url", args=[attached.pk])
    ).status_code == 404
    assert client.delete(
        reverse("admin-machine-service-file-detail", args=[attached.pk])
    ).status_code == 404

    assert client.post(
        _action_url(completed, "collect"), {}, format="json"
    ).status_code == 200
    completed.refresh_from_db()
    assert completed.status == MachineServiceRequest.Status.COLLECTED
    assert completed.collected_by_id == actor.id


def test_machine_service_conversion_preserves_visibility_statuses():
    makerspace = make_makerspace("org-service-status")
    requester = make_user("org-service-status-requester")
    row = _request(
        makerspace,
        _machine(makerspace, "org-service-status-machine"),
        requester,
        MachineServiceRequest.Status.COMPLETED,
        "status",
    )
    authorized = _org_collector("org-service-status", makerspace)
    local = _local_without_actions("org-service-status-local", makerspace)
    outsider = make_user("org-service-status-outsider")

    assert _client(authorized).get(_detail_url(row)).status_code == 200
    assert _client(local).get(_detail_url(row)).status_code == 403
    assert _client(outsider).get(_detail_url(row)).status_code == 404
    assert _client(local).get(_list_url(makerspace)).status_code == 403
    assert _client(outsider).get(_list_url(makerspace)).status_code == 404

    hidden = make_makerspace(
        "org-service-status-hidden", superadmin_access_enabled=False
    )
    hidden_actor = _org_collector("org-service-hidden", hidden)
    hidden_row = _request(
        hidden,
        _machine(hidden, "org-service-hidden-machine"),
        requester,
        MachineServiceRequest.Status.COMPLETED,
        "hidden",
    )
    assert _client(hidden_actor).get(_detail_url(hidden_row)).status_code == 404
    assert _client(hidden_actor).get(_list_url(hidden)).status_code == 404
    archived = make_makerspace("org-service-status-archived")
    archived_actor = _org_collector("org-service-archived", archived)
    archived_row = _request(
        archived,
        _machine(archived, "org-service-archived-machine"),
        requester,
        MachineServiceRequest.Status.COMPLETED,
        "archived",
    )
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    assert _client(archived_actor).get(_detail_url(archived_row)).status_code == 404
    assert _client(archived_actor).get(_list_url(archived)).status_code == 404
