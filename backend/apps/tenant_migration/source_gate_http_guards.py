"""Authenticated HTTP boundary checks used by the source-gate AST guard."""

import ast
from pathlib import Path

from .source_gate_ast import APPS_DIR, calls_gate, trees


MUTATING_METHODS = frozenset({"post", "put", "patch", "delete"})
GATE_AUTHENTICATOR = "SpaceWorksJWTAuthentication"
# The one other authenticator a mutating view may declare -- singly, never mixed. It is
# admitted only because `_validate_device_authenticator` proves its late-gate order.
DEVICE_AUTHENTICATOR = "DeviceAuthentication"
DEVICE_AUTHENTICATION_MODULE = ("devices", "authentication.py")


def validate_authenticated_http_boundary(apps_dir, error_class):
    for path, module, tree in trees(apps_dir):
        if "views" not in path.stem and path.stem != "api_views":
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                _validate_view_class(node, module, error_class)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _validate_function_view(node, module, error_class)
    if _uses_device_authenticator(apps_dir):
        _validate_device_authenticator(apps_dir, error_class)
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
    if authenticators == {DEVICE_AUTHENTICATOR} and len(assignment.value.elts) == 1:
        return
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


def _uses_device_authenticator(apps_dir):
    for path, _module, tree in trees(apps_dir):
        if "views" not in path.stem and path.stem != "api_views":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == DEVICE_AUTHENTICATOR:
                return True
    return False


def _validate_device_authenticator(apps_dir, error_class):
    """The device tenant must be selected BEFORE the late gate, and the gate must be real.

    `DeviceAuthentication.authenticate` resolves the Device, assigns
    `request.selected_makerspace_id` from it, then calls `_assert_source_gate(request)`,
    which must call `assert_request_write_allowed`. A gate call before selection would
    check no tenant at all and let a device write into a frozen source.
    """
    path = Path(apps_dir).joinpath(*DEVICE_AUTHENTICATION_MODULE)
    if not path.is_file():
        raise error_class("DeviceAuthentication is declared but its module is missing")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    klass = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef) and node.name == DEVICE_AUTHENTICATOR),
        None,
    )
    method = klass and next(
        (node for node in klass.body
         if isinstance(node, ast.FunctionDef) and node.name == "authenticate"),
        None,
    )
    hook = next(
        (node for node in tree.body
         if isinstance(node, ast.FunctionDef) and node.name == "_assert_source_gate"),
        None,
    )
    if method is None or hook is None:
        raise error_class("DeviceAuthentication lacks authenticate/_assert_source_gate")
    if not any(
        isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        == "assert_request_write_allowed"
        for node in ast.walk(hook)
    ):
        raise error_class("DeviceAuthentication's gate hook does not assert the source gate")
    selections = [
        node.lineno for node in ast.walk(method)
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr == "selected_makerspace_id"
            for target in node.targets
        )
    ]
    gates = [
        node.lineno for node in ast.walk(method)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_assert_source_gate"
    ]
    if not gates:
        raise error_class("DeviceAuthentication never calls the late source gate")
    if not selections or min(gates) < min(selections):
        raise error_class("DeviceAuthentication calls the source gate before selecting a tenant")
