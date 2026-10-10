from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest
from tests.hardware_requests.loan_policy_helpers import setup_loan

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_renewals_cannot_exceed_policy_or_emit_two_audits():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    space, member, _, _, loan, _, _ = setup_loan("concurrent-renew")
    start = Barrier(2)

    def renew():
        close_old_connections()
        try:
            actor = User.objects.get(pk=member.pk)
            request = HardwareRequest.objects.get(pk=loan.pk)
            start.wait(timeout=15)
            try:
                workflow.renew_loan(actor, request)
                return "renewed"
            except ValidationError as exc:
                return str(exc.detail["code"])
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(renew) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(results) == ["renewal_limit", "renewed"]
    loan.refresh_from_db()
    assert loan.renewal_count == 1
    assert AuditLog.objects.filter(makerspace=space, action="request.renewed").count() == 1
