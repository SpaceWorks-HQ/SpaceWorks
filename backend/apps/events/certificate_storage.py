import hashlib

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.object_storage import delete_all_versions


class CertificateStorageUnavailable(Exception):
    pass


def _client(endpoint):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
        ),
    )


def staging_key(object_key):
    return f"staging/{object_key}"


def store_immutable_pdf(object_key, content):
    digest = hashlib.sha256(content).hexdigest()
    size = len(content)
    client = _client(settings.AWS_S3_ENDPOINT_URL)
    try:
        existing = _digest_or_none(client, object_key)
        if existing is not None:
            if existing != (size, digest):
                raise CertificateStorageUnavailable(
                    "The certificate key already contains different bytes."
                )
            return size, digest
        staged = staging_key(object_key)
        client.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=staged,
            Body=content,
            ContentType="application/pdf",
        )
        client.copy_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CopySource={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": staged},
            Key=object_key,
            ContentType="application/pdf",
            MetadataDirective="REPLACE",
        )
        if _digest_or_none(client, object_key) != (size, digest):
            raise CertificateStorageUnavailable("Certificate promotion verification failed.")
        delete_all_versions(client, bucket=settings.AWS_STORAGE_BUCKET_NAME, key=staged)
        return size, digest
    except (BotoCoreError, ClientError, OSError) as exc:
        raise CertificateStorageUnavailable from exc


def presigned_download(object_key):
    try:
        return _client(settings.AWS_S3_PUBLIC_ENDPOINT_URL).generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": object_key,
                "ResponseContentType": "application/pdf",
            },
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise CertificateStorageUnavailable from exc


def _digest_or_none(client, key):
    try:
        response = client.get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: response["Body"].read(64 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()
