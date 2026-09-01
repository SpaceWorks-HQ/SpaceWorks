import pytest
from botocore.exceptions import ClientError

from apps.object_storage import delete_all_versions


def test_delete_all_versions_removes_versions_and_delete_markers():
    deleted_batches = []
    listed_pages = []

    class Client:
        def list_object_versions(self, **kwargs):
            listed_pages.append(kwargs)
            if len(listed_pages) == 1:
                return {
                    "Versions": [
                        {"Key": "exports/job.zip", "VersionId": "current"},
                        {"Key": "exports/job.zip.tmp", "VersionId": "unrelated"},
                    ],
                    "IsTruncated": True,
                    "NextKeyMarker": "exports/job.zip",
                    "NextVersionIdMarker": "current",
                }
            return {
                "Versions": [
                    {"Key": "exports/job.zip", "VersionId": "previous"},
                ],
                "DeleteMarkers": [
                    {"Key": "exports/job.zip", "VersionId": "marker"}
                ],
                "IsTruncated": False,
            }

        def delete_objects(self, **kwargs):
            deleted_batches.append(kwargs)

        def delete_object(self, **_kwargs):
            raise AssertionError("A versioned key must not receive a bare delete")

    delete_all_versions(Client(), bucket="private", key="exports/job.zip")

    assert listed_pages == [
        {"Bucket": "private", "Prefix": "exports/job.zip"},
        {
            "Bucket": "private",
            "Prefix": "exports/job.zip",
            "KeyMarker": "exports/job.zip",
            "VersionIdMarker": "current",
        },
    ]
    assert deleted_batches == [{
        "Bucket": "private",
        "Delete": {
            "Objects": [
                {"Key": "exports/job.zip", "VersionId": "current"},
                {"Key": "exports/job.zip", "VersionId": "previous"},
                {"Key": "exports/job.zip", "VersionId": "marker"},
            ],
            "Quiet": True,
        },
    }]


def test_delete_all_versions_falls_back_when_listing_is_unsupported():
    deleted = []

    class Client:
        def list_object_versions(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "NotImplemented", "Message": "unsupported"}},
                "ListObjectVersions",
            )

        def delete_object(self, **kwargs):
            deleted.append(kwargs)

    delete_all_versions(Client(), bucket="private", key="exports/job.zip")

    assert deleted == [{"Bucket": "private", "Key": "exports/job.zip"}]


def test_delete_all_versions_can_require_provable_version_deletion():
    deleted = []

    class Client:
        def list_object_versions(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "NotImplemented", "Message": "unsupported"}},
                "ListObjectVersions",
            )

        def delete_object(self, **kwargs):
            deleted.append(kwargs)

    with pytest.raises(ClientError):
        delete_all_versions(
            Client(),
            bucket="private",
            key="evidence/photo.jpg",
            require_version_listing=True,
        )

    assert deleted == []


def test_delete_all_versions_propagates_access_denied_without_bare_delete():
    deleted = []

    class Client:
        def list_object_versions(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "ListObjectVersions",
            )

        def delete_object(self, **kwargs):
            deleted.append(kwargs)

    with pytest.raises(ClientError) as raised:
        delete_all_versions(Client(), bucket="private", key="exports/job.zip")

    assert raised.value.response["Error"]["Code"] == "AccessDenied"
    assert deleted == []


def test_delete_all_versions_propagates_failure_after_first_listing_page():
    deleted = []
    calls = 0

    class Client:
        def list_object_versions(self, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "Versions": [
                        {"Key": "exports/job.zip", "VersionId": "current"}
                    ],
                    "IsTruncated": True,
                    "NextKeyMarker": "exports/job.zip",
                    "NextVersionIdMarker": "current",
                }
            raise ClientError(
                {"Error": {"Code": "NotImplemented", "Message": "unsupported"}},
                "ListObjectVersions",
            )

        def delete_object(self, **kwargs):
            deleted.append(kwargs)

    with pytest.raises(ClientError) as raised:
        delete_all_versions(Client(), bucket="private", key="exports/job.zip")

    assert raised.value.response["Error"]["Code"] == "NotImplemented"
    assert calls == 2
    assert deleted == []
