import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.evidence.checks import check_storage_bucket_separation
from config.storage_validation import assert_distinct_storage_buckets


def test_startup_settings_validation_rejects_equal_bucket_names():
    with pytest.raises(ImproperlyConfigured, match="must differ"):
        assert_distinct_storage_buckets("shared-private", "shared-private")


def test_system_check_rejects_equal_bucket_names():
    with override_settings(
        AWS_STORAGE_BUCKET_NAME="shared-private",
        PUBLIC_IMAGE_BUCKET="shared-private",
    ):
        errors = check_storage_bucket_separation(None)

    assert [error.id for error in errors] == ["evidence.E001"]
