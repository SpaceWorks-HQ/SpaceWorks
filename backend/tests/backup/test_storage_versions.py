from datetime import datetime, timezone
from io import BytesIO

from botocore.exceptions import ClientError

from apps.backup import storage


def test_versioned_capture_pins_retained_bytes_behind_a_delete_marker(
    monkeypatch, tmp_path
):
    calls = []

    class Client:
        def head_object(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )

        def list_object_versions(self, **_kwargs):
            return {
                "Versions": [{
                    "Key": "events/1/image.jpg",
                    "VersionId": "retained-version",
                    "LastModified": datetime(2026, 8, 16, tzinfo=timezone.utc),
                }],
                "IsTruncated": False,
            }

        def get_object(self, **kwargs):
            calls.append(kwargs)
            return {"Body": BytesIO(b"retained bytes"), "Metadata": {}}

    monkeypatch.setattr(storage, "client", lambda: Client())
    destination = tmp_path / "image.jpg"

    item = storage.download_object(
        "public-images", "events/1/image.jpg", destination, versioned=True
    )

    assert destination.read_bytes() == b"retained bytes"
    assert item["version_id"] == "retained-version"
    assert calls == [{
        "Bucket": "public-images",
        "Key": "events/1/image.jpg",
        "VersionId": "retained-version",
    }]
