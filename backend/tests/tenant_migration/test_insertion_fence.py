import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.encryption.models import PiiMakerspaceWriteFence
from apps.encryption.write_fence import PiiWriteFenced, close_makerspace, fence_operation
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


def test_tenant_import_fence_allows_only_its_matching_transaction():
    space = Makerspace.objects.create(
        name="Import Fence", slug=f"import-fence-{uuid.uuid4().hex[:8]}"
    )
    actor = get_user_model().objects.create_user(
        username=f"import-fence-actor-{uuid.uuid4().hex[:8]}"
    )
    request = HardwareRequest.objects.create(
        makerspace=space,
        requester=actor,
        requester_username=actor.username,
        requester_name="Before import",
    )
    operation_id = close_makerspace(
        space.pk, PiiMakerspaceWriteFence.OperationKind.TENANT_IMPORT, actor.pk
    )

    request.requester_name = "ordinary session"
    with pytest.raises(PiiWriteFenced):
        request.save(update_fields=["requester_name"])

    with transaction.atomic(), fence_operation(operation_id):
        request.requester_name = "matching operation"
        request.save(update_fields=["requester_name"])

    with transaction.atomic(), fence_operation(uuid.uuid4()):
        request.requester_name = "different operation"
        with pytest.raises(PiiWriteFenced):
            request.save(update_fields=["requester_name"])

    request.refresh_from_db()
    assert request.requester_name == "matching operation"
