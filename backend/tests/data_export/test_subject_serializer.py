"""Subject-export input errors must remain DRF error dictionaries."""

import pytest

from apps.data_export.subject_views import SubjectExportCreateSerializer


@pytest.mark.parametrize("payload", [
    {"user_id": 12}, {"makerspace_id": 34}, [], "", None,
])
def test_subject_export_refuses_nonempty_or_nonobject_payloads(payload):
    serializer = SubjectExportCreateSerializer(data=payload)
    assert not serializer.is_valid()
    assert set(serializer.errors) == {"non_field_errors"}
    assert serializer.errors["non_field_errors"]


def test_subject_export_accepts_only_an_empty_object():
    serializer = SubjectExportCreateSerializer(data={})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {}
