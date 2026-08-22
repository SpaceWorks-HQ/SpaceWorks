"""Executable ownership registry for the Lane E readable-main projection."""

from dataclasses import dataclass
from enum import StrEnum

from django.apps import apps
from django.db import connections, models
from django.db.models import Q

from apps.backup.recipient_selection import BackupBuildError
from apps.data_export.datasets import DATASET_SPECS
from apps.data_export.models import MODELS
from apps.data_export.types import TenantPredicate


class RowDisposition(StrEnum):
    RETAIN_GLOBAL = "retain_global"
    COPY_TO_SLICE = "copy_to_slice"


class BoundaryDisposition(StrEnum):
    DROP_ROW_TO_SLICE = "drop_row_to_slice"
    PROJECT_NULL_TO_SLICE = "project_null_to_slice"


@dataclass(frozen=True)
class TableRule:
    model: type[models.Model]
    disposition: RowDisposition
    predicate: object | None


@dataclass(frozen=True)
class BoundaryRule:
    source_rule: TableRule
    source_model: type[models.Model]
    field: models.Field
    target_rule: TableRule
    target_predicate: TenantPredicate
    disposition: BoundaryDisposition


# Physical tables with no Django model behind them. Declared explicitly, with the
# reason, so that a new unmanaged table is a build failure instead of a silent
# passenger in the operator-readable main.
#   carry_rows=True  -> rows survive into the readable main
#   carry_rows=False -> the table is kept but emptied during projection
NON_MODEL_TABLES = {
    # Schema bookkeeping. Carries no tenant data and the restored deployment
    # needs it to know which migrations have run.
    "django_migrations": True,
    # Django's DatabaseCache table, used when no CACHE_URL is configured. It
    # holds throttle counters keyed by caller identity, so its rows are
    # tenant-derived even though no model owns them. Cache state is ephemeral
    # and rebuilds itself, so it is emptied rather than reasoned about
    # row-by-row -- carrying it would put sovereign identities back into the
    # readable main this projection exists to clear.
    "spaceworks_cache": False,
}
DJANGO_RUNTIME_TABLES = frozenset(NON_MODEL_TABLES)
EMPTIED_NON_MODEL_TABLES = frozenset(
    table for table, carry_rows in NON_MODEL_TABLES.items() if not carry_rows
)
PROJECT_GLOBAL_BOUNDARIES = frozenset({
    ("backup.BackupArchive", "makerspace"),
    ("backup.RestoreRollbackObject", "makerspace"),
    ("tenant_migration.TenantImportJob", "target_makerspace"),
})

# Auto-created M2M models are physical tables even though they have no project
# model class of their own. Keep this literal so a new authority-bearing M2M
# cannot silently inherit a deployment-global disposition.
AUTO_CREATED_M2M_TABLES = {
    "accounts_user_groups": (RowDisposition.RETAIN_GLOBAL, None),
    "accounts_user_user_permissions": (RowDisposition.RETAIN_GLOBAL, None),
    "auth_group_permissions": (RowDisposition.RETAIN_GLOBAL, None),
}

# These rows are tenant-owned for deployment projection even though manager data
# export deliberately omits them. W8 replaces the source-broker row with a sealed
# recipient payload; retaining it in the readable main would preserve platform
# unwrap capability for sovereign mapped ciphertext.
SPECIAL_TENANT_TABLES = {
    "encryption.MakerspaceEncryptionKey": TenantPredicate(("makerspace",)),
}


def table_rules():
    """Return one explicit disposition for every model-backed physical table."""
    result = []
    seen_tables = set()
    missing = []
    discovered_auto_created = set()
    for model in apps.get_models(include_auto_created=True):
        options = model._meta
        if options.proxy or not options.managed:
            continue
        label = options.label
        if options.auto_created:
            declared = AUTO_CREATED_M2M_TABLES.get(options.db_table)
            if declared is None:
                missing.append(f"{label} ({options.db_table})")
                continue
            disposition, predicate = declared
            if (disposition == RowDisposition.COPY_TO_SLICE) != (predicate is not None):
                raise BackupBuildError(
                    "Readable-main auto-created M2M disposition is incomplete for "
                    f"{options.db_table}."
                )
            discovered_auto_created.add(options.db_table)
        elif options.app_config.name.startswith("apps."):
            if label not in MODELS:
                missing.append(label)
                continue
            special_predicate = SPECIAL_TENANT_TABLES.get(label)
            spec = DATASET_SPECS.get(label)
            disposition = (
                RowDisposition.COPY_TO_SLICE
                if spec is not None or special_predicate is not None
                else RowDisposition.RETAIN_GLOBAL
            )
            predicate = (
                special_predicate
                or (
                    TenantPredicate((spec[1].any_paths[0],))
                    if spec is not None else None
                )
            )
        else:
            disposition, predicate = RowDisposition.RETAIN_GLOBAL, None
        if options.db_table in seen_tables:
            raise BackupBuildError(
                f"Readable-main registry repeats table {options.db_table}."
            )
        seen_tables.add(options.db_table)
        result.append(TableRule(model, disposition, predicate))
    if missing:
        raise BackupBuildError(
            "Readable-main registry lacks physical-table disposition(s): "
            + ", ".join(sorted(missing))
        )
    stale_auto_created = set(AUTO_CREATED_M2M_TABLES) - discovered_auto_created
    if stale_auto_created:
        raise BackupBuildError(
            "Readable-main auto-created M2M registry has absent table(s): "
            + ", ".join(sorted(stale_auto_created))
        )
    return tuple(result)


def boundary_rules(rules):
    """Declare every non-owner FK that can point into a sliced table."""
    by_model = {rule.model: rule for rule in rules}
    owner_paths = {
        rule.model: {rule.predicate.any_paths[0]}
        for rule in rules
        if rule.disposition == RowDisposition.COPY_TO_SLICE
    }
    changed = True
    while changed:
        changed = False
        for source_rule in rules:
            for field in source_rule.model._meta.concrete_fields:
                target_paths = owner_paths.get(
                    getattr(field.remote_field, "model", None)
                )
                if not target_paths or _is_canonical_owner(source_rule, field):
                    continue
                if _boundary_disposition(source_rule, field) != (
                    BoundaryDisposition.DROP_ROW_TO_SLICE
                ):
                    continue
                target = getattr(field.remote_field, "model", None)
                if (
                    source_rule.model in owner_paths
                    and getattr(target._meta, "label", "") != "makerspaces.Makerspace"
                ):
                    continue
                paths = owner_paths.setdefault(source_rule.model, set())
                prefixed = {
                    field.name if path in {"pk", "id"} else f"{field.name}__{path}"
                    for path in target_paths
                }
                if not prefixed.issubset(paths):
                    paths.update(prefixed)
                    changed = True
    result = []
    projected_global = set()
    for source_rule in rules:
        for field in source_rule.model._meta.concrete_fields:
            target = getattr(field.remote_field, "model", None)
            target_rule = by_model.get(target)
            target_paths = owner_paths.get(target)
            if target_rule is None or not target_paths:
                continue
            if _is_canonical_owner(source_rule, field):
                continue
            disposition = _boundary_disposition(source_rule, field)
            if (
                source_rule.disposition == RowDisposition.RETAIN_GLOBAL
                and disposition == BoundaryDisposition.PROJECT_NULL_TO_SLICE
            ):
                if not field.null:
                    raise BackupBuildError(
                        f"Readable-main boundary cannot null {source_rule.model._meta.label}.{field.name}."
                    )
                projected_global.add((source_rule.model._meta.label, field.name))
            result.append(BoundaryRule(
                source_rule=source_rule,
                source_model=source_rule.model,
                field=field,
                target_rule=target_rule,
                target_predicate=TenantPredicate(tuple(sorted(target_paths))),
                disposition=disposition,
            ))
    if projected_global != PROJECT_GLOBAL_BOUNDARIES:
        raise BackupBuildError(
            "Readable-main global boundary registry drift: "
            f"declared={sorted(PROJECT_GLOBAL_BOUNDARIES)}, "
            f"discovered={sorted(projected_global)}."
        )
    return tuple(result)


def boundary_queryset(rule, using, makerspace_ids):
    targets = rule.target_rule.model._base_manager.using(using).filter(
        sovereign_q(rule.target_predicate, makerspace_ids)
    ).values("pk")
    queryset = rule.source_model._base_manager.using(using).filter(
        **{f"{rule.field.attname}__in": targets}
    )
    if rule.source_rule.disposition == RowDisposition.COPY_TO_SLICE:
        queryset = queryset.exclude(
            sovereign_q(rule.source_rule.predicate, makerspace_ids)
        )
    return queryset


def _is_canonical_owner(rule, field):
    return bool(
        rule.predicate is not None
        and field.name == rule.predicate.any_paths[0].split("__", 1)[0]
    )


def _boundary_disposition(source_rule, field):
    if source_rule.disposition == RowDisposition.RETAIN_GLOBAL:
        key = (source_rule.model._meta.label, field.name)
        return (
            BoundaryDisposition.PROJECT_NULL_TO_SLICE
            if key in PROJECT_GLOBAL_BOUNDARIES
            else BoundaryDisposition.DROP_ROW_TO_SLICE
        )
    return (
        BoundaryDisposition.PROJECT_NULL_TO_SLICE
        if field.null
        else BoundaryDisposition.DROP_ROW_TO_SLICE
    )


def sovereign_q(predicate, makerspace_ids):
    query = Q(pk__in=())
    for makerspace_id in makerspace_ids:
        for path in predicate.any_paths:
            lookup = path if path in {"pk", "id"} else f"{path}_id"
            query |= Q(**{lookup: makerspace_id})
    return query


def assert_catalog_matches(using, rules):
    connection = connections[using]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
              FROM pg_catalog.pg_class c
              JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
             ORDER BY c.relname
            """
        )
        actual = {row[0] for row in cursor.fetchall()}
    expected = {rule.model._meta.db_table for rule in rules} | DJANGO_RUNTIME_TABLES
    if actual != expected:
        missing = sorted(actual - expected)
        stale = sorted(expected - actual)
        raise BackupBuildError(
            "Readable-main physical-table registry drift: "
            f"unclassified={missing}, absent={stale}."
        )
