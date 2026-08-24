"""AST guard for archived-style tenant exclusions.

This guard sees statically written ``archived_at`` attributes/lookups and calls to the
known archived-ID helpers in Python files under ``apps/``. It cannot see dynamically
constructed ORM lookup names, raw SQL, or policy implemented outside Python, so those
still require review and behavioural tests.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import apps.makerspaces


APPS_DIR = Path(apps.makerspaces.__file__).resolve().parent.parent
ARCHIVE_HELPERS = {"archived_makerspace_ids", "_exclude_archived_ids"}
SERVABILITY_CALLS = {
    "is_servable",
    "servable_q",
    "servable_queryset",
    "unservable_makerspace_ids",
    "archived_or_inactive_makerspace_ids",
    *ARCHIVE_HELPERS,
}

# These operations deliberately need rows that normal traffic must not serve.
EXEMPTIONS = {
    # The policy implementation necessarily contains the raw fields it centralizes.
    ("makerspaces/servability.py", "is_servable"),
    ("makerspaces/servability.py", "archived_or_inactive_makerspace_ids"),
    # Archive recovery must inspect and clear archived_at, and purge must inspect it.
    ("makerspaces/lifecycle_archive.py", "unarchive"),
    ("makerspaces/lifecycle_purge.py", "purge"),
    # /control/ is the superadmin recovery surface for archived/import-failed rows.
    ("makerspaces/admin.py", "ArchivedFilter.queryset"),
    ("makerspaces/admin.py", "MakerspaceAdmin.has_delete_permission"),
    ("makerspaces/admin.py", "MakerspaceAdmin.archived"),
    # Members may discover old charges only after a tenant has actually been archived.
    ("payments/views_member.py", "ArchivedPaymentDiscoveryView.get"),
    # The abort-recovery twin of `unarchive`: cutover archives the source, so reopening
    # it after a failed migration must both inspect and clear `archived_at`. Routing it
    # through the servability policy would make the one operation that undoes a cutover
    # refuse to run on the only state it is ever called in. It is not a hole -- it
    # requires a superuser, a locked pairing, and a verified single-use abort receipt
    # from the target proving it reached ABORTED and can no longer activate.
    ("tenant_migration/cutover.py", "reopen_source"),
}


@dataclass(frozen=True, order=True)
class Site:
    path: str
    function: str
    line: int


def _call_name(node):
    return getattr(node.func, "attr", None) or getattr(node.func, "id", None)


def _archive_style(node, parents):
    if isinstance(node, ast.keyword):
        parent = parents.get(node)
        return bool(
            node.arg
            and "archived_at" in node.arg
            and isinstance(parent, ast.Call)
            and _call_name(parent)
            in {"exclude", "filter", "get", "get_object_or_404", "update"}
        )
    if isinstance(node, ast.Attribute):
        return node.attr == "archived_at"
    return isinstance(node, ast.Call) and _call_name(node) in ARCHIVE_HELPERS


def _function_name(node, parents):
    names = []
    current = node
    while True:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(current.name)
        if current not in parents:
            break
        current = parents[current]
    return ".".join(reversed(names)) or "<module>"


def _sites():
    sites = []
    functions = {}
    for path in APPS_DIR.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        relative = path.relative_to(APPS_DIR).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[(relative, _function_name(node, parents))] = node
            if _archive_style(node, parents):
                sites.append(
                    Site(relative, _function_name(node, parents), node.lineno)
                )
    return sites, functions


def _consults_servability(function):
    return any(
        isinstance(node, ast.Call) and _call_name(node) in SERVABILITY_CALLS
        for node in ast.walk(function)
    )


def test_every_archived_style_site_participates_in_tenant_servability():
    sites, functions = _sites()
    uncovered = {
        (site.path, site.function)
        for site in sites
        if (site.path, site.function) not in EXEMPTIONS
        and not _consults_servability(functions[(site.path, site.function)])
    }
    assert not uncovered, (
        "Archived-style tenant exclusions must call the canonical servability policy "
        f"or be documented as recovery/import exemptions: {sorted(uncovered)}"
    )

    discovered_exemptions = {
        (site.path, site.function)
        for site in sites
        if (site.path, site.function) in EXEMPTIONS
    }
    assert discovered_exemptions == EXEMPTIONS, (
        "Stale tenant-servability exemptions must be removed: "
        f"{sorted(EXEMPTIONS - discovered_exemptions)}"
    )


def test_legacy_archived_helpers_delegate_to_unservable_policy():
    _, functions = _sites()
    helper = functions[("accounts/rbac.py", "archived_makerspace_ids")]
    assert any(
        isinstance(node, ast.Call) and _call_name(node) == "unservable_makerspace_ids"
        for node in ast.walk(helper)
    )
    subtractor = functions[("accounts/rbac.py", "_exclude_archived_ids")]
    assert any(
        isinstance(node, ast.Call) and _call_name(node) == "archived_makerspace_ids"
        for node in ast.walk(subtractor)
    )
