"""AST drift guard for id-bearing ``audit.record(..., meta=...)`` paths."""

import ast
from dataclasses import dataclass
from pathlib import Path

import apps
from apps.data_export.models import EXPORTED_MODELS

from .audit_references import (
    AUDIT_META_REFERENCES,
    AuditReferenceDisposition,
)


APPS_DIR = Path(apps.__file__).resolve().parent


@dataclass(frozen=True)
class UnresolvableAuditCall:
    path: str
    line: int
    reason: str


@dataclass(frozen=True)
class AuditMetaDiscovery:
    actions: frozenset[str]
    meta_paths: frozenset[tuple[str, str]]
    id_paths: frozenset[tuple[str, str]]
    unresolvable: tuple[UnresolvableAuditCall, ...]


def looks_like_audit_id(key, value):
    """Narrow ID rule: id/_id/_ids names, ``.pk``, or values_list("pk")."""
    name_match = key == "id" or key.endswith(("_id", "_ids"))
    pk_attribute = isinstance(value, ast.Attribute) and value.attr == "pk"
    pk_values_list = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "values_list"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "pk"
        for node in ast.walk(value)
    )
    return name_match or pk_attribute or pk_values_list


def discover_audit_meta_references(apps_dir=APPS_DIR):
    actions, meta_paths, id_paths, unresolved = set(), set(), set(), []
    for path in sorted(Path(apps_dir).rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        module_aliases, direct_names = _audit_record_imports(tree)
        for node in ast.walk(tree):
            if not _is_record_call(node, module_aliases, direct_names):
                continue
            action_node = _argument(node, 1, "action")
            action = (
                action_node.value
                if isinstance(action_node, ast.Constant)
                and isinstance(action_node.value, str)
                else None
            )
            meta = _argument(node, None, "meta")
            if action is None:
                unresolved.append(_unresolved(path, node, "dynamic action"))
            else:
                actions.add(action)
            if meta is None:
                continue
            if not isinstance(meta, ast.Dict):
                unresolved.append(_unresolved(path, node, "non-literal meta"))
                continue
            if action is not None:
                _discover_dict(action, meta, "", meta_paths, id_paths, unresolved, path, node)
    return AuditMetaDiscovery(
        frozenset(actions), frozenset(meta_paths), frozenset(id_paths), tuple(unresolved)
    )


def validate_audit_meta_references(declarations=AUDIT_META_REFERENCES, *, discovery=None):
    from .reference_guards import ReferenceRegistryError

    discovery = discovery or discover_audit_meta_references()
    missing = discovery.id_paths - set(declarations)
    if missing:
        raise ReferenceRegistryError(
            f"audit meta ID paths drifted; missing={sorted(missing)}"
        )
    for edge, declaration in declarations.items():
        if declaration.disposition is AuditReferenceDisposition.REMAP:
            if declaration.target_model_label not in EXPORTED_MODELS:
                raise ReferenceRegistryError(
                    f"audit meta remap target is not exported: {edge} -> "
                    f"{declaration.target_model_label}"
                )
    return discovery


def _discover_dict(action, mapping, prefix, meta_paths, id_paths, unresolved, path, call):
    for key_node, value in zip(mapping.keys, mapping.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            unresolved.append(_unresolved(path, call, "non-literal meta key"))
            continue
        key = key_node.value
        current = f"{prefix}.{key}" if prefix else key
        meta_paths.add((action, current))
        if looks_like_audit_id(key, value):
            id_paths.add((action, current))
        if isinstance(value, ast.Dict):
            _discover_dict(action, value, current, meta_paths, id_paths, unresolved, path, call)
        elif isinstance(value, ast.DictComp) and _dict_key_looks_like_id(value.key):
            id_paths.add((action, f"{current}.<keys>"))


def _dict_key_looks_like_id(node):
    return (
        isinstance(node, ast.Attribute) and node.attr == "pk"
    ) or (
        isinstance(node, ast.Name)
        and (node.id == "id" or node.id.endswith(("_id", "_ids")))
    )


def _audit_record_imports(tree):
    module_aliases, direct_names = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "apps.audit":
            module_aliases.update(
                item.asname or item.name
                for item in node.names
                if item.name == "services"
            )
        elif node.module == "apps.audit.services":
            direct_names.update(
                item.asname or item.name for item in node.names if item.name == "record"
            )
    return module_aliases, direct_names


def _is_record_call(node, module_aliases, direct_names):
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id in direct_names
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "record"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module_aliases
    )


def _argument(call, position, keyword):
    if position is not None and len(call.args) > position:
        return call.args[position]
    return next((item.value for item in call.keywords if item.arg == keyword), None)


def _unresolved(path, node, reason):
    try:
        relative = str(path.relative_to(APPS_DIR))
    except ValueError:
        relative = str(path)
    return UnresolvableAuditCall(relative, node.lineno, reason)
