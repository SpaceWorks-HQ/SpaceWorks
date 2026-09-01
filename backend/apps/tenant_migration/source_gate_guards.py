"""AST totality guards for source-gate mutation entry points."""

import ast
from pathlib import Path

from .gate_policy import (
    ADMIN_ACTION_EXEMPTIONS,
    HTTP_ANONYMOUS_EXEMPTIONS,
    HTTP_ANONYMOUS_PARTICIPANTS,
    HTTP_EXEMPTIONS,
    LIFECYCLE_EXEMPTIONS,
    OBJECT_MUTATION_PARTICIPANTS,
    TASK_EXEMPTIONS,
    TASK_INTERNAL_PARTICIPANTS,
    TASK_TENANT_RESOLVERS,
)
from .source_gate_ast import (
    APPS_DIR,
    EntryPoint,
    admin_action_names as _admin_action_names,
    all_functions as _all_functions,
    calls_gate as _calls_gate,
    class_allows_anonymous as _class_allows_anonymous,
    has_incompatible_task_base as _has_incompatible_task_base,
    is_object_mutation as _is_object_mutation,
    is_storage_primitive as _is_storage_primitive,
    owner as _owner,
    parents as _parents,
    relative as _relative,
    storage_imports as _storage_imports,
    task_call as _task_call,
    task_name as _task_name,
    trees as _trees,
    url_names as _url_names,
)
from .source_gate_fanout_guards import validate_fanout_gate_coverage
from .source_gate_http_guards import validate_authenticated_http_boundary


MUTATING_HTTP_METHODS = frozenset({"post", "put", "patch", "delete"})


class SourceGateCoverageError(AssertionError):
    pass


def discover_tasks(apps_dir=APPS_DIR):
    entries = []
    for path, module, tree in _trees(apps_dir):
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorator = next((item for item in node.decorator_list if _task_call(item)), None)
            if decorator is None:
                continue
            name = _task_name(decorator) or f"{module}.{node.name}"
            entries.append(EntryPoint(
                name, _relative(path, apps_dir), node.lineno,
                not _has_incompatible_task_base(decorator),
            ))
    return tuple(sorted(entries))


def validate_task_coverage(
    apps_dir=APPS_DIR, *, exemptions=TASK_EXEMPTIONS,
    resolvers=TASK_TENANT_RESOLVERS, internal=TASK_INTERNAL_PARTICIPANTS,
):
    entries = discover_tasks(apps_dir)
    actual = {entry.target for entry in entries}
    declarations = set(exemptions) | set(resolvers) | set(internal)
    _exact("Celery task", actual, declarations)
    broken = [entry.target for entry in entries if not entry.participates]
    if broken:
        raise SourceGateCoverageError(
            f"Celery tasks override TenantGateTask: {sorted(broken)}"
        )
    if Path(apps_dir).resolve() == APPS_DIR:
        celery_config = APPS_DIR.parent / "config" / "celery.py"
        expected = "apps.tenant_migration.task_gate:TenantGateTask"
        if expected not in celery_config.read_text(encoding="utf-8-sig"):
            raise SourceGateCoverageError(
                "Celery's default task class is not TenantGateTask"
            )
    return entries


def discover_webhooks(apps_dir=APPS_DIR):
    entries = []
    for path, module, tree in _trees(apps_dir):
        for klass in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            if "Webhook" not in klass.name:
                continue
            for method in klass.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if method.name not in MUTATING_HTTP_METHODS:
                    continue
                parameters = {arg.arg for arg in method.args.args}
                participates = bool(
                    parameters & {"makerspace_id", "makerspace_slug", "public_code"}
                    or _calls_gate(method)
                )
                entries.append(EntryPoint(
                    f"{module}.{klass.name}.{method.name}",
                    _relative(path, apps_dir), method.lineno, participates,
                ))
    return tuple(sorted(entries))


def validate_webhook_coverage(apps_dir=APPS_DIR):
    entries = discover_webhooks(apps_dir)
    actual = {entry.target for entry in entries}
    exemptions = {
        "apps.payments.views_connect.StripeConnectWebhookView.post":
            HTTP_EXEMPTIONS["stripe-connect-webhook"],
    }
    stale = set(exemptions) - actual
    if stale:
        raise SourceGateCoverageError(f"stale webhook exemptions: {sorted(stale)}")
    missing = {
        entry.target for entry in entries
        if not entry.participates and entry.target not in exemptions
    }
    if missing:
        raise SourceGateCoverageError(
            f"webhooks bypass source-gate participation: {sorted(missing)}"
        )
    return entries


def discover_anonymous_http_mutations(apps_dir=APPS_DIR):
    entries = []
    for path, module, tree in _trees(apps_dir):
        if "views" not in path.stem and path.stem != "api_views":
            continue
        for klass in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            if not _class_allows_anonymous(klass):
                continue
            for method in klass.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if method.name not in MUTATING_HTTP_METHODS:
                    continue
                parameters = {arg.arg for arg in method.args.args}
                entries.append(EntryPoint(
                    f"{module}.{klass.name}.{method.name}",
                    _relative(path, apps_dir), method.lineno,
                    bool(
                        parameters
                        & {"makerspace_id", "makerspace_slug", "public_code"}
                        or _calls_gate(method)
                    ),
                ))
    return tuple(sorted(entries))


def validate_http_coverage(
    apps_dir=APPS_DIR, *, exemptions=HTTP_ANONYMOUS_EXEMPTIONS,
    participants=HTTP_ANONYMOUS_PARTICIPANTS,
):
    validate_authenticated_http_boundary(apps_dir, SourceGateCoverageError)
    entries = discover_anonymous_http_mutations(apps_dir)
    actual = {entry.target for entry in entries}
    declared = set(exemptions) | set(participants)
    stale = declared - actual
    if stale:
        raise SourceGateCoverageError(
            f"stale anonymous HTTP declarations: {sorted(stale)}"
        )
    missing = {
        entry.target for entry in entries
        if not entry.participates and entry.target not in declared
    }
    if missing:
        raise SourceGateCoverageError(
            f"anonymous HTTP mutations bypass source-gate participation: {sorted(missing)}"
        )
    if Path(apps_dir).resolve() == APPS_DIR:
        stale_routes = set(HTTP_EXEMPTIONS) - set(_url_names(apps_dir))
        if stale_routes:
            raise SourceGateCoverageError(
                f"stale HTTP route exemptions: {sorted(stale_routes)}"
            )
        declared_actions = {
            target.rsplit(".", 1)[-1] for target in ADMIN_ACTION_EXEMPTIONS
        }
        stale_actions = declared_actions - set(_admin_action_names(apps_dir))
        if stale_actions:
            raise SourceGateCoverageError(
                f"stale admin action exemptions: {sorted(stale_actions)}"
            )
        admin_gate = APPS_DIR.parent / "config" / "admin_source_gate.py"
        if "assert_write_allowed" not in admin_gate.read_text(encoding="utf-8-sig"):
            raise SourceGateCoverageError("Django admin lacks late tenant gate resolution")
        functions = _all_functions(apps_dir)
        hook = functions.get("apps.accounts.authentication._assert_source_gate")
        if hook is None or not any(
            isinstance(node, ast.Call)
            and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
            == "assert_request_write_allowed"
            for node in ast.walk(hook)
        ):
            raise SourceGateCoverageError(
                "authenticated DRF routes lack the late source-gate assertion"
            )
    return entries


def validate_lifecycle_exemptions(apps_dir=APPS_DIR):
    actual = set()
    functions = _all_functions(apps_dir)
    for target in LIFECYCLE_EXEMPTIONS:
        if target not in functions:
            raise SourceGateCoverageError(f"stale lifecycle exemption: {target}")
        if _calls_gate(functions[target]):
            raise SourceGateCoverageError(
                f"lifecycle exemption unexpectedly participates: {target}"
            )
        actual.add(target)
    expected = {
        "apps.encryption.services.rotate_dek",
        "apps.encryption.services.disable_dek",
        "apps.encryption.services.rewrap_dek",
        "apps.makerspaces.lifecycle_archive.archive",
        "apps.makerspaces.lifecycle_archive._archive_locked",
        "apps.makerspaces.lifecycle_purge.purge",
    }
    _exact("lifecycle exemption", actual, expected)
    return frozenset(actual)


def discover_object_mutations(apps_dir=APPS_DIR):
    entries = []
    for path, module, tree in _trees(apps_dir):
        if _is_storage_primitive(module) or ".migrations." in f".{module}.":
            continue
        storage_aliases, direct_names = _storage_imports(tree)
        parents = _parents(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if not _is_object_mutation(call, storage_aliases, direct_names):
                continue
            owner = _owner(call, parents)
            if owner is None:
                continue
            target, owner_node = owner
            full_target = f"{module}.{target}"
            participates = (
                _calls_gate(owner_node)
                or "views" in path.stem
                or path.stem.startswith("admin")
                or path.stem == "tasks"
                or module.startswith("apps.backup.")
                or full_target in LIFECYCLE_EXEMPTIONS
            )
            entries.append(EntryPoint(
                full_target, _relative(path, apps_dir), call.lineno, participates,
            ))
    return tuple(sorted(entries))


def validate_object_mutation_coverage(
    apps_dir=APPS_DIR, *, participants=OBJECT_MUTATION_PARTICIPANTS
):
    entries = discover_object_mutations(apps_dir)
    actual = {entry.target for entry in entries}
    stale = set(participants) - actual
    if stale:
        raise SourceGateCoverageError(
            f"stale object-mutation participation: {sorted(stale)}"
        )
    missing = sorted({
        entry.target for entry in entries
        if not entry.participates
        and entry.target not in participants
    })
    if missing:
        raise SourceGateCoverageError(
            f"object mutations bypass source-gate participation: {missing}"
        )
    return entries


def validate_source_gate_coverage(apps_dir=APPS_DIR):
    return {
        "tasks": validate_task_coverage(apps_dir),
        "webhooks": validate_webhook_coverage(apps_dir),
        "http": validate_http_coverage(apps_dir),
        "lifecycle": validate_lifecycle_exemptions(apps_dir),
        "objects": validate_object_mutation_coverage(apps_dir),
        "fanouts": validate_fanout_gate_coverage(apps_dir, error_class=SourceGateCoverageError),
    }


def _exact(kind, actual, declared):
    if actual != declared:
        raise SourceGateCoverageError(
            f"{kind} registry drifted; missing={sorted(actual - declared)}, "
            f"stale={sorted(declared - actual)}"
        )
