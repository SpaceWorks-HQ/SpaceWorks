"""Authenticated HTTP boundary checks used by the source-gate AST guard."""

import ast
from pathlib import Path

from .source_gate_ast import APPS_DIR, calls_gate, trees


MUTATING_METHODS = frozenset({"post", "put", "patch", "delete"})
GATE_AUTHENTICATOR = "SpaceWorksJWTAuthentication"


def validate_authenticated_http_boundary(apps_dir, error_class):
    for path, module, tree in trees(apps_dir):
        if "views" not in path.stem and path.stem != "api_views":
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                _validate_view_class(node, module, error_class)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _validate_function_view(node, module, error_class)
    if Path(apps_dir).resolve() == APPS_DIR:
        settings_path = APPS_DIR.parent / "config" / "settings.py"
        expected = "apps.accounts.authentication.SpaceWorksJWTAuthentication"
        if expected not in settings_path.read_text(encoding="utf-8-sig"):
            raise error_class(
                "DRF's default authenticator does not enforce the source gate"
            )


def _validate_view_class(klass, module, error_class):
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in MUTATING_METHODS
        for node in klass.body
    ):
        return
    assignment = next(
        (
            node for node in klass.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "authentication_classes"
                for target in node.targets
            )
        ),
        None,
    )
    if assignment is None or not assignment.value.elts:
        return
    authenticators = {
        getattr(item, "id", None) or getattr(item, "attr", None)
        for item in assignment.value.elts
    }
    if authenticators != {GATE_AUTHENTICATOR}:
        raise error_class(
            f"mutating view overrides the gate authenticator: "
            f"{module}.{klass.name} -> {sorted(authenticators)}"
        )


def _validate_function_view(function, module, error_class):
    methods = set()
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if getattr(decorator.func, "id", None) != "api_view":
            continue
        if decorator.args and isinstance(decorator.args[0], (ast.List, ast.Tuple)):
            methods.update(
                str(item.value).lower()
                for item in decorator.args[0].elts
                if isinstance(item, ast.Constant)
            )
    if methods & MUTATING_METHODS and not calls_gate(function):
        raise error_class(
            f"mutating function view bypasses source gate: {module}.{function.name}"
        )
