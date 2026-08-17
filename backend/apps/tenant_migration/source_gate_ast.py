"""Shared AST primitives for source-gate coverage discovery."""

import ast
from dataclasses import dataclass
from pathlib import Path

import apps


APPS_DIR = Path(apps.__file__).resolve().parent
OBJECT_MUTATION_NAMES = frozenset({
    "copy_object", "delete_archive", "delete_object", "delete_staged_file", "finalize_file",
    "finalize_receipt_upload", "finalize_upload", "presigned_upload",
    "put_bytes", "release_public_image_on_commit",
})


@dataclass(frozen=True, order=True)
class EntryPoint:
    target: str
    path: str
    line: int
    participates: bool


def trees(apps_dir):
    root = Path(apps_dir)
    for path in sorted(root.rglob("*.py")):
        if "migrations" in path.parts or "__pycache__" in path.parts:
            continue
        module = "apps." + ".".join(
            path.relative_to(root).with_suffix("").parts
        )
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        yield path, module, tree


def url_names(apps_dir):
    root = Path(apps_dir)
    paths = set(root.rglob("urls*.py"))
    config_urls = root.parent / "config" / "urls.py"
    if config_urls.exists():
        paths.add(config_urls)
    names = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            value = next((kw.value for kw in call.keywords if kw.arg == "name"), None)
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.add(value.value)
    return frozenset(names)


def admin_action_names(apps_dir):
    names = set()
    for path in Path(apps_dir).rglob("admin*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(
                    isinstance(item, ast.Call)
                    and getattr(item.func, "attr", None) == "action"
                    for item in node.decorator_list
                ):
                    names.add(node.name)
    return frozenset(names)


def class_allows_anonymous(klass):
    for node in klass.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        if "authentication_classes" in names and not node.value.elts:
            return True
        if "permission_classes" in names and any(
            getattr(item, "id", None) == "AllowAny" for item in node.value.elts
        ):
            return True
    return False


def relative(path, root):
    return str(path.relative_to(root))


def task_call(node):
    call = node if isinstance(node, ast.Call) else None
    func = call.func if call else node
    return (
        getattr(func, "id", None) == "shared_task"
        or getattr(func, "attr", None) == "task"
    )


def task_name(node):
    if not isinstance(node, ast.Call):
        return None
    value = next((kw.value for kw in node.keywords if kw.arg == "name"), None)
    return value.value if isinstance(value, ast.Constant) else None


def has_incompatible_task_base(node):
    if not isinstance(node, ast.Call):
        return False
    base = next((kw.value for kw in node.keywords if kw.arg == "base"), None)
    return base is not None and getattr(base, "id", None) != "TenantGateTask"


def calls_gate(node):
    return any(
        isinstance(item, ast.Call)
        and (getattr(item.func, "id", None) or getattr(item.func, "attr", None))
        in {"assert_write_allowed", "source_archive_write", "tenant_write"}
        for item in ast.walk(node)
    )


def all_functions(apps_dir):
    result = {}
    for _path, module, tree in trees(apps_dir):
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result[f"{module}.{node.name}"] = node
    return result


def storage_imports(tree):
    modules, direct = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = node.module or ""
            for item in node.names:
                local = item.asname or item.name
                if item.name in {"storage", "public_image_storage", "service_storage"}:
                    modules.add(local)
                if "storage" in source and item.name in OBJECT_MUTATION_NAMES:
                    direct.add(local)
        elif isinstance(node, ast.Import):
            for item in node.names:
                if "storage" in item.name:
                    modules.add(item.asname or item.name.rsplit(".", 1)[-1])
    return modules, direct


def is_object_mutation(call, modules, direct):
    if isinstance(call.func, ast.Name):
        return call.func.id in direct
    if not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr not in OBJECT_MUTATION_NAMES:
        return False
    root = call.func.value
    while isinstance(root, (ast.Attribute, ast.Call)):
        root = root.func if isinstance(root, ast.Call) else root.value
    return isinstance(root, ast.Name) and root.id in modules


def is_storage_primitive(module):
    return module.endswith((".storage", ".public_image_storage", ".service_storage"))


def parents(tree):
    result = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            result[child] = parent
    return result


def owner(node, parent_map):
    names = []
    current = node
    owner_node = None
    while current in parent_map:
        current = parent_map[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(current.name)
            if owner_node is None and isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                owner_node = current
    return (".".join(reversed(names)), owner_node) if owner_node else None
