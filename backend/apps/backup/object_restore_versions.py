"""Deterministic version-history handling for object restore rollback."""


class ObjectRestoreError(RuntimeError):
    pass


def current_delete_marker_version_id(client, bucket, key):
    for item in _iter_key_versions_newest_first(client, bucket, key):
        if item["is_delete_marker"]:
            return item["version_id"]
        raise ObjectRestoreError(
            f"Could not identify the current delete marker for {key}."
        )
    return ""


def delete_versions_newer_than_marker(client, *, bucket, key, marker_version_id):
    newer_versions = []
    for item in _iter_key_versions_newest_first(client, bucket, key):
        if item["version_id"] == marker_version_id:
            for version_id in newer_versions:
                client.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
            return
        newer_versions.append(item["version_id"])
    raise ObjectRestoreError(
        f"Rollback delete marker {marker_version_id} was not found for {key}."
    )


def _iter_key_versions_newest_first(client, bucket, key):
    # MaxKeys=1 preserves S3's version order without merging the separately
    # returned Versions and DeleteMarkers arrays or comparing timestamps.
    params = {"Bucket": bucket, "Prefix": key, "MaxKeys": 1}
    while True:
        page = client.list_object_versions(**params)
        for field, is_delete_marker in (
            ("Versions", False),
            ("DeleteMarkers", True),
        ):
            for item in page.get(field, ()):
                if item.get("Key") == key:
                    yield {
                        "version_id": item["VersionId"],
                        "is_delete_marker": is_delete_marker,
                    }
        if not page.get("IsTruncated"):
            return
        params = {
            "Bucket": bucket,
            "Prefix": key,
            "MaxKeys": 1,
            "KeyMarker": page.get("NextKeyMarker"),
            "VersionIdMarker": page.get("NextVersionIdMarker"),
        }
        params = {name: value for name, value in params.items() if value is not None}
