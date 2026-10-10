from django.urls import reverse
from rest_framework.test import APIClient

from apps.hardware_requests.models import ReplayCommand
from tests.hardware_requests.replay_helpers import envelope, execute, prepare


def failed_issue(env):
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, data).status_code == 200
    assert execute(env, data).data["code"] == "box_scan_required"
    return ReplayCommand.objects.get(client_command_id=data["client_command_id"])


def staff_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def recovery_url(name, **kwargs):
    return reverse(f"hardware_requests:admin-kiosk-replay-{name}", kwargs=kwargs)


def resolve(client, row, code="acknowledged_no_change", replacement=None):
    body = {"resolution_code": code}
    if replacement:
        body["replacement_command_id"] = str(replacement.pk)
    return client.post(recovery_url("resolve", pk=row.pk), body, format="json")


def successful_replacement(env):
    assigned = envelope(env)
    assert prepare(env, assigned).status_code == execute(env, assigned).status_code == 200
    issue = envelope(env, "reviewed_issue", {"request_id": env.request.pk, "remark": "New correction photo"})
    assert prepare(env, issue).status_code == execute(env, issue).status_code == 200
    return ReplayCommand.objects.get(client_command_id=issue["client_command_id"])
