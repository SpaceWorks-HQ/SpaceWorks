"""Historical review uses current per-kind RBAC, independent of kiosk capability."""

from functools import reduce
from operator import or_

from django.db.models import Q

from apps.accounts import rbac
from apps.hardware_requests.models_replay import ReplayCommand

OPERATION_ACTIONS = {
    "assign_box": rbac.Action.ASSIGN_BOX,
    "reviewed_issue": rbac.Action.ISSUE_REQUEST,
    "reviewed_return": rbac.Action.RETURN_REQUEST,
    "direct_handout": rbac.Action.ISSUE_DIRECT_LOAN,
    "direct_return": rbac.Action.RETURN_REQUEST,
}


def visible_replays(user):
    predicates = []
    for kind, action in OPERATION_ACTIONS.items():
        scope = rbac.makerspaces_for_action(user, action)
        predicates.append(Q(operation_kind=kind) if scope is rbac.ALL else
                          Q(operation_kind=kind, makerspace_id__in=scope))
    return rbac.hide_from_superadmin(
        user, ReplayCommand.objects.filter(reduce(or_, predicates)), "makerspace_id",
    )


def subject_context(command):
    """A dependent direct return can have failed before dispatch recorded its loan."""
    request_id, loan_id = command.subject_request_id, command.subject_loan_id
    previous = command.predecessor
    while command.operation_kind == "direct_return" and loan_id is None and previous is not None:
        loan_id = previous.result_loan_id
        previous = previous.predecessor
    return request_id, loan_id
