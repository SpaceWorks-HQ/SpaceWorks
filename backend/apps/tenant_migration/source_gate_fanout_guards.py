"""AST guard for deployment-wide jobs that take a source gate per tenant."""

import ast

from .gate_policy import FANOUT_GATE_PARTICIPANTS
from .source_gate_ast import APPS_DIR, all_functions, parents


def validate_fanout_gate_coverage(
    apps_dir=APPS_DIR, *, participants=FANOUT_GATE_PARTICIPANTS, error_class=AssertionError
):
    """Require tenant loops to use the skip-and-count boundary, never a raw gate."""
    functions = all_functions(apps_dir)
    declared = set(participants)
    stale = declared - set(functions)
    if stale:
        raise error_class(f"stale fan-out gate participation: {sorted(stale)}")

    helper_callers = {
        target
        for target, node in functions.items()
        if _calls_named(node, "fanout_tenant_write")
    }
    if helper_callers != declared:
        raise error_class(
            "fan-out gate participant registry drifted; "
            f"missing={sorted(helper_callers - declared)}, "
            f"stale={sorted(declared - helper_callers)}"
        )

    unsafe = []
    unsafe_helper_usage = []
    for target, function in functions.items():
        parent_map = parents(function)
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if name == "fanout_tenant_write":
                if not _has_loop_parent(call, parent_map, function) or not (
                    _continues_when_skipped(call, parent_map)
                ):
                    unsafe_helper_usage.append(target)
                continue
            if name not in {"boundary_tenant_write", "tenant_write"}:
                continue
            if _has_loop_parent(call, parent_map, function):
                unsafe.append(target)
                break
    if unsafe:
        raise error_class(
            f"tenant fan-outs bypass skip-and-count gate boundary: {sorted(unsafe)}"
        )
    if unsafe_helper_usage:
        raise error_class(
            "tenant fan-outs ignore the frozen-tenant skip signal: "
            f"{sorted(unsafe_helper_usage)}"
        )
    return frozenset(helper_callers)


def _calls_named(node, name):
    return any(
        isinstance(item, ast.Call)
        and (getattr(item.func, "id", None) or getattr(item.func, "attr", None)) == name
        for item in ast.walk(node)
    )


def _has_loop_parent(node, parent_map, function):
    current = node
    while current in parent_map:
        current = parent_map[current]
        if isinstance(current, (ast.For, ast.AsyncFor)):
            return True
        if current is function:
            return False
    return False


def _continues_when_skipped(call, parent_map):
    with_item = parent_map.get(call)
    with_node = parent_map.get(with_item)
    if not isinstance(with_item, ast.withitem) or not isinstance(with_node, ast.With):
        return False
    variable = with_item.optional_vars
    if not isinstance(variable, ast.Name) or not with_node.body:
        return False
    first = with_node.body[0]
    return (
        isinstance(first, ast.If)
        and isinstance(first.test, ast.UnaryOp)
        and isinstance(first.test.op, ast.Not)
        and isinstance(first.test.operand, ast.Name)
        and first.test.operand.id == variable.id
        and len(first.body) == 1
        and isinstance(first.body[0], ast.Continue)
    )
