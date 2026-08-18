"""Private attachment storage for machine service requests."""

from dataclasses import dataclass
import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.evidence.storage import StorageUnavailable
from apps.maker_file_formats import (
    STRICT_MIME_BY_EXTENSION,
    allowed_pair,
    extension_from_name,
    has_required_signature,
    sniff_pdf_or_image,
)
from apps.machines import storage as machine_storage
from apps.machines.models import Machine, MachineServiceRequest, ServiceRequestFile
from apps.machines.service_file_policies import get_policy, policy_for_machine, policy_for_queue
from apps.makerspaces import limits

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceObjectValidationResult:
    size: int
    content_type: str


def _client():
    return machine_storage._client()


def _public_client():
    return machine_storage._public_client()


def service_object_key(makerspace_id, context_id):
    return f"machine/{makerspace_id}/{context_id}/service/{uuid.uuid4().hex}"


def staging_key(object_key):
    return machine_storage.staging_key(object_key)


def validate_upload_declaration(policy, filename, content_type):
    ext = extension_from_name(filename)
    if not allowed_pair(ext, content_type, policy.allowed_extensions, policy.allowed_mimes):
        raise ValidationError({"filename": "Unsupported attachment extension or content type."}, code="invalid_attachment")


def policy_for_file(file):
    """Use the immutable policy snapshot retained with the staged file."""
    return get_policy(file.file_policy_name, file.file_policy_version)


def create_staged_file(service_request, *, actor, filename, content_type):
    if service_request.queue_id:
        queue = service_request.queue
        machine, policy, context_id = None, policy_for_queue(queue), f"queue-{queue.pk}"
        makerspace = queue.makerspace
    else:
        machine = Machine.objects.get(pk=service_request.bucket.machine_id)
        queue, policy, context_id, makerspace = None, policy_for_machine(machine), machine.pk, machine.makerspace
    validate_upload_declaration(policy, filename, content_type)
    upload = ServiceRequestFile.objects.create(
        makerspace=makerspace, machine=machine, queue=queue,
        kind=ServiceRequestFile.Kind.ATTACHMENT,
        object_key=service_object_key(makerspace.pk, context_id),
        content_type=content_type.lower().strip(),
        original_filename=filename,
        owner_user_id=actor.pk,
        file_policy_name=policy.name,
        file_policy_version=policy.version,
    )
    try:
        presigned = presigned_upload(upload.object_key, upload.content_type, policy.max_bytes)
    except Exception:
        upload.delete()
        raise
    audit.record(
        actor, "machine_service.file_staged", makerspace=makerspace,
        target=upload, meta={"request_id": service_request.pk, "file_id": upload.pk},
    )
    return upload, presigned


def create_staged_queue_file(queue, *, actor, filename, content_type, kind=ServiceRequestFile.Kind.MODEL):
    """Stage a public queued-service file before its request exists.

    Public printing uses this during the B4 compatibility period: the queue is
    already authoritative, while the request is only created after upload.
    """
    policy = policy_for_queue(queue)
    validate_upload_declaration(policy, filename, content_type)
    upload = ServiceRequestFile.objects.create(
        makerspace=queue.makerspace, queue=queue,
        kind=kind,
        object_key=service_object_key(queue.makerspace_id, f"queue-{queue.pk}"),
        content_type=content_type.lower().strip(), original_filename=filename,
        owner_user_id=actor.pk, file_policy_name=policy.name,
        file_policy_version=policy.version,
    )
    try:
        presigned = presigned_upload(upload.object_key, upload.content_type, policy.max_bytes)
    except Exception:
        upload.delete()
        raise
    audit.record(
        actor, "machine_service.file_staged", makerspace=queue.makerspace,
        target=upload, meta={"queue_id": queue.pk, "file_id": upload.pk},
    )
    return upload, presigned


def presigned_upload(object_key, content_type, max_bytes):
    try:
        if settings.STORAGE_PRESIGN_METHOD == "put":
            url = _public_client().generate_presigned_url(
                "put_object", Params={
                    "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                    "Key": staging_key(object_key), "ContentType": content_type,
                }, ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
            )
            return {"url": url, "method": "PUT", "headers": {"Content-Type": content_type}}
        return _public_client().generate_presigned_post(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=object_key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc


def object_size(object_key):
    try:
        response = _client().head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=object_key)
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code")
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise StorageUnavailable from exc
    except BotoCoreError as exc:
        raise StorageUnavailable from exc
    return int(response["ContentLength"])


def delete_object(object_key):
    try:
        _client().delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=object_key)
    except (BotoCoreError, ClientError):
        logger.exception("Failed to delete machine service object %s.", object_key)


def cleanup_upload(object_key):
    delete_object(object_key)
    delete_object(staging_key(object_key))


def finalize_upload(object_key, max_bytes):
    if settings.STORAGE_PRESIGN_METHOD != "put":
        return object_size(object_key)
    final_size = object_size(object_key)
    if final_size is not None:
        delete_object(staging_key(object_key))
        return final_size
    source = staging_key(object_key)
    size = object_size(source)
    if size is None or not 1 <= size <= max_bytes:
        return size
    try:
        _client().copy_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CopySource={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": source},
            Key=object_key,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc
    delete_object(source)
    final_size = object_size(object_key)
    if final_size is None or not 1 <= final_size <= max_bytes:
        delete_object(object_key)
    return final_size


def validate_service_object(file, policy):
    size = object_size(file.object_key)
    if size is None:
        raise ValidationError({"file_id": "Uploaded attachment was not found."}, code="invalid_attachment")
    if not 1 <= size <= policy.max_bytes:
        raise ValidationError({"file_id": "Uploaded attachment exceeds the size limit."}, code="invalid_attachment")
    try:
        response = _client().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=file.object_key)
        data = response["Body"].read(policy.max_bytes)
        stored_content_type = str(response.get("ContentType", "")).lower().strip()
    except (BotoCoreError, ClientError, OSError) as exc:
        raise StorageUnavailable from exc
    ext = extension_from_name(file.original_filename)
    if not allowed_pair(ext, stored_content_type, policy.allowed_extensions, policy.allowed_mimes):
        raise ValidationError({"file_id": "Attachment extension and content type do not match."}, code="invalid_attachment")
    sniffed = sniff_pdf_or_image(data)
    strict_mime = STRICT_MIME_BY_EXTENSION.get(ext)
    if strict_mime or sniffed:
        if not strict_mime or stored_content_type != strict_mime or sniffed != strict_mime:
            raise ValidationError({"file_id": "Attachment content does not match its extension."}, code="invalid_attachment")
        content_type = sniffed
    elif not has_required_signature(ext, data):
        raise ValidationError({"file_id": "Attachment signature is invalid."}, code="invalid_attachment")
    else:
        content_type = stored_content_type
    return ServiceObjectValidationResult(size=size, content_type=content_type)


def finalize_file(service_request, *, file_id, actor):
    try:
        file = ServiceRequestFile.objects.select_related(
            "makerspace", "machine__makerspace", "queue__makerspace"
        ).get(pk=file_id, owner_user_id=actor.pk)
    except ServiceRequestFile.DoesNotExist as exc:
        raise ValidationError(
            {"file_id": "Attachment is unavailable for this request."},
            code="invalid_attachment",
        ) from exc
    # Refuse an already-attached file before touching object storage so a retry or
    # concurrent finalize can never delete the live object a committed record points at.
    if file.service_request_id is not None or file.attached_at is not None:
        raise ValidationError({"file_id": "Attachment is unavailable for this request."}, code="invalid_attachment")
    policy = policy_for_file(file)
    try:
        size = finalize_upload(file.object_key, policy.max_bytes)
        if size is None or not 1 <= size <= policy.max_bytes:
            raise ValidationError({"file_id": "Uploaded attachment is invalid."}, code="invalid_attachment")
        result = validate_service_object(file, policy)
        with transaction.atomic():
            locked_request = MachineServiceRequest.objects.select_for_update(of=("self",)).select_related(
                "bucket__machine__makerspace", "queue__makerspace"
            ).get(pk=service_request.pk)
            locked_file = ServiceRequestFile.objects.select_for_update().get(pk=file.pk)
            if (
                locked_file.owner_user_id != actor.pk
                or locked_file.service_request_id is not None
                or locked_file.makerspace_id != locked_request.makerspace_id
                or (locked_request.queue_id and locked_file.queue_id != locked_request.queue_id)
                or (locked_request.bucket_id and locked_file.machine_id != locked_request.bucket.machine_id)
            ):
                raise ValidationError({"file_id": "Attachment is unavailable for this request."}, code="invalid_attachment")
            limits.add_storage(locked_request.makerspace, result.size)
            locked_file.service_request = locked_request
            locked_file.attached_at = timezone.now()
            locked_file.size_bytes = result.size
            locked_file.content_type = result.content_type
            locked_file.save(update_fields=["service_request", "attached_at", "size_bytes", "content_type"])
            audit.record(
                actor, "machine_service.file_attached", makerspace=locked_request.makerspace,
                target=locked_file, meta={"request_id": locked_request.pk, "file_id": locked_file.pk, "size_bytes": result.size},
            )
            return locked_file
    except Exception:
        # Only compensate a still-staged upload; if a concurrent finalize won the
        # race and attached this file, leave its object intact.
        if ServiceRequestFile.objects.filter(
            pk=file.pk, service_request__isnull=True, attached_at__isnull=True
        ).exists():
            cleanup_upload(file.object_key)
        raise


def delete_staged_file(file, *, actor):
    with transaction.atomic():
        locked = ServiceRequestFile.objects.select_for_update().select_related("makerspace").get(pk=file.pk)
        if locked.service_request_id is not None or locked.attached_at is not None:
            raise ValidationError({"file_id": "Attached files cannot be deleted."}, code="invalid_attachment")
        audit.record(
            actor, "machine_service.file_deleted", makerspace=locked.makerspace,
            target=locked, meta={"file_id": locked.pk, "size_bytes": locked.size_bytes},
        )
        limits.free_storage(locked.makerspace, locked.size_bytes)
        object_key = locked.object_key
        locked.delete()
    cleanup_upload(object_key)


def presigned_get_url(object_key):
    try:
        return _public_client().generate_presigned_url(
            "get_object", Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": object_key},
            ExpiresIn=settings.EVIDENCE_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable from exc
