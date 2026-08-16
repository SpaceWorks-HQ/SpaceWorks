"""Resolve the portable user closure without importing source account authority."""

from dataclasses import dataclass
import hashlib

from apps.accounts.models import User
from apps.accounts.username_allocation import allocate_username

from .archive_stream import database_value
from .insertion_errors import IdentityResolutionError, PrimaryKeyMapUnavailable
from .models_import_job import ImportIdentityDecision
from .transaction_state import require_import_transaction

REQUIRED_TABLE = "tenant_import_required_identity"


@dataclass(frozen=True)
class IdentityResolutionReport:
    linked: int
    created: int
    preexisting_global_authority: tuple[dict[str, object], ...]
    linked_global_state_fingerprint: bytes


class RequiredIdentitySet:
    """Deduplicated required source users held in transaction-local PostgreSQL."""

    def __init__(self):
        self.connection = require_import_transaction()
        self.pending = set()
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TEMPORARY TABLE {REQUIRED_TABLE} "
                "(source_user_id text PRIMARY KEY) ON COMMIT DROP"
            )

    def add_row(self, model, row):
        if model._meta.label not in {"audit.AuditLog", "makerspaces.Makerspace"}:
            for field in model._meta.local_concrete_fields:
                if (
                    field.is_relation
                    and field.related_model is not None
                    and field.related_model._meta.label == "accounts.User"
                    and row.get(field.attname)
                ):
                    self.add(row[field.attname])
        if model._meta.label == "machines.ServiceRequestFile" and row.get(
            "owner_user_id"
        ):
            self.add(row["owner_user_id"])

    def add(self, source_user_id):
        self.pending.add(str(source_user_id))
        if len(self.pending) >= 500:
            self.flush()

    def flush(self):
        if not self.pending:
            return
        with self.connection.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO {REQUIRED_TABLE} (source_user_id) VALUES (%s) "
                "ON CONFLICT DO NOTHING",
                [(value,) for value in self.pending],
            )
        self.pending.clear()

    def contains(self, source_user_id):
        self.flush()
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {REQUIRED_TABLE} WHERE source_user_id=%s",
                [str(source_user_id)],
            )
            return cursor.fetchone() is not None

    def count(self):
        self.flush()
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {REQUIRED_TABLE}")
            return cursor.fetchone()[0]


def preallocate_walk_in_ids(job, pk_map, required):
    """Reserve CREATE_WALK_IN user IDs before any imported row is inserted."""
    create_ids = (
        source_id
        for source_id in job.identity_decisions.filter(
            identity_resolution=ImportIdentityDecision.IdentityResolution.CREATE_WALK_IN
        )
        .values_list("source_user_id", flat=True)
        .iterator(chunk_size=500)
        if required.contains(source_id)
    )
    pk_map.reserve(User, create_ids)


def resolve_identities(archive, job, pk_map, required):
    """Validate the complete closure, create bounded walk-ins, and populate its PK map."""
    seen_count = 0
    for source in archive.rows("accounts.User"):
        source_id = source["id"]
        if not required.contains(source_id):
            continue
        seen_count += 1
        decision = _required_decision(job, source_id)
        if decision.identity_resolution == decision.IdentityResolution.LINK_EXISTING:
            if decision.target_user is None:
                raise IdentityResolutionError(
                    f"Source user {source_id} has an incomplete LINK_EXISTING decision."
                )
        elif decision.identity_resolution == decision.IdentityResolution.CREATE_WALK_IN:
            if decision.target_user_id is not None:
                raise IdentityResolutionError(
                    f"Source user {source_id} has an invalid CREATE_WALK_IN decision."
                )
            pk_map.lookup(User, source_id)
        else:
            raise IdentityResolutionError(
                f"Source user {source_id} has an unsupported identity decision."
            )
    if required.count() != seen_count:
        raise IdentityResolutionError(
            "A retained source identity is absent from global/users.csv."
        )

    linked = created = 0
    reported = []
    linked_state_fingerprint = 0
    user_model = User
    for source in archive.rows("accounts.User"):
        source_id = source["id"]
        if not required.contains(source_id):
            continue
        decision = _required_decision(job, source_id)
        if decision.identity_resolution == decision.IdentityResolution.LINK_EXISTING:
            target = decision.target_user
            if target is None:
                raise IdentityResolutionError(
                    f"Source user {source_id} has an incomplete LINK_EXISTING decision."
                )
            pk_map.add_many(user_model, [(source_id, target.pk)])
            linked += 1
            linked_state_fingerprint ^= _authority_record_fingerprint(
                target.pk, target.is_superuser, target.is_staff, target.role
            )
            if target.is_superuser or target.role == User.Role.SUPERADMIN:
                reported.append(
                    {
                        "source_user_id": source_id,
                        "target_user_id": target.pk,
                        "kind": "target_global_superadmin",
                    }
                )
            continue
        _create_walk_in(source, pk_map.lookup(user_model, source_id))
        created += 1
    return IdentityResolutionReport(
        linked,
        created,
        tuple(reported),
        linked_state_fingerprint.to_bytes(32, "big"),
    )


def _required_decision(job, source_id):
    try:
        return job.identity_decisions.select_related("target_user").get(
            source_user_id=source_id
        )
    except ImportIdentityDecision.DoesNotExist as exc:
        raise IdentityResolutionError(
            f"Source user {source_id} has no identity decision."
        ) from exc


def _create_walk_in(source, target_pk):
    date_joined = database_value(User._meta.get_field("date_joined"), source["date_joined"])

    def create(username):
        user = User(
            pk=target_pk,
            username=username,
            email="",
            first_name=source.get("first_name", ""),
            last_name=source.get("last_name", ""),
            display_name=source.get("display_name", ""),
            phone=source.get("phone", ""),
            phone_e164="",
            phone_verified_at=None,
            email_verified_at=None,
            date_joined=date_joined,
            role=User.Role.REQUESTER,
            access_status=User.AccessStatus.ACTIVE,
            is_walk_in=True,
            is_staff=False,
            is_superuser=False,
            is_active=True,
        )
        user.set_unusable_password()
        user.save(force_insert=True)
        return user

    return allocate_username(source.get("username", "member"), create=create)


def decision_for_source_user(job, source_user_id):
    try:
        return job.identity_decisions.get(source_user_id=str(source_user_id))
    except ImportIdentityDecision.DoesNotExist as exc:
        raise IdentityResolutionError(
            f"Source user {source_user_id} has no identity decision."
        ) from exc


def linked_authority_fingerprint(job, pk_map):
    fingerprint = 0
    decisions = job.identity_decisions.filter(
        identity_resolution=ImportIdentityDecision.IdentityResolution.LINK_EXISTING
    ).select_related("target_user")
    for decision in decisions.iterator(chunk_size=500):
        try:
            pk_map.lookup(User, decision.source_user_id)
        except PrimaryKeyMapUnavailable:
            continue
        target = decision.target_user
        if target is None:
            raise IdentityResolutionError("A LINK_EXISTING decision lost its target.")
        fingerprint ^= _authority_record_fingerprint(
            target.pk, target.is_superuser, target.is_staff, target.role
        )
    return fingerprint.to_bytes(32, "big")


def _authority_record_fingerprint(user_id, is_superuser, is_staff, role):
    payload = f"{user_id}:{int(is_superuser)}:{int(is_staff)}:{role}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")
