"""Constraint-enabled row ordering with a narrow nullable-cycle escape hatch."""

from collections import defaultdict, deque
from dataclasses import dataclass

from .tenant_dump_errors import TenantDumpDependencyError
from .tenant_dump_raw import SanitizedRow


@dataclass(frozen=True)
class DeferredForeignKey:
    identity: tuple[str, object]
    column: str
    value: object


@dataclass(frozen=True)
class RowLoadPlan:
    rows: tuple[SanitizedRow, ...]
    deferred_foreign_keys: tuple[DeferredForeignKey, ...]

    @property
    def used_two_pass(self):
        return bool(self.deferred_foreign_keys)


def plan_row_load(rows, *, resolved_pks=None):
    """Order actual incoming rows; defer only edges inside actual nullable SCCs."""
    resolved_pks = resolved_pks or {}
    row_by_identity = {row.identity: row for row in rows}
    if len(row_by_identity) != len(rows):
        raise TenantDumpDependencyError("Lane D input contains a duplicate row identity.")

    dependencies = {identity: set() for identity in row_by_identity}
    edge_fields = defaultdict(list)
    rewritten = []
    for row in rows:
        values = dict(row.values)
        for field in row.model._meta.concrete_fields:
            if not field.is_relation or field.related_model is None:
                continue
            value = values[field.column]
            if value is None:
                continue
            target_label = field.related_model._meta.label
            mapped = resolved_pks.get((target_label, value), value)
            values[field.column] = mapped
            target = (target_label, mapped)
            if target in row_by_identity:
                dependencies[row.identity].add(target)
                edge_fields[(row.identity, target)].append(field)
        rewritten.append(SanitizedRow(row.model, row.source_pk, values))
    row_by_identity = {row.identity: row for row in rewritten}

    cyclic_components = _cyclic_components(dependencies)
    deferred = []
    ignored_edges = set()
    for component in cyclic_components:
        for source in component:
            for target in dependencies[source] & component:
                fields = edge_fields[(source, target)]
                if any(not field.null for field in fields):
                    raise TenantDumpDependencyError(
                        "Lane D incoming rows contain a non-nullable FK cycle: "
                        + ", ".join(sorted(label for label, _pk in component))
                    )
                ignored_edges.add((source, target))
                row = row_by_identity[source]
                values = dict(row.values)
                for field in fields:
                    deferred.append(
                        DeferredForeignKey(source, field.column, values[field.column])
                    )
                    values[field.column] = None
                row_by_identity[source] = SanitizedRow(
                    row.model, row.source_pk, values
                )

    order = _topological_order(dependencies, ignored_edges)
    return RowLoadPlan(
        rows=tuple(row_by_identity[identity] for identity in order),
        deferred_foreign_keys=tuple(deferred),
    )


def _topological_order(dependencies, ignored_edges):
    remaining = {
        source: {
            target
            for target in targets
            if (source, target) not in ignored_edges
        }
        for source, targets in dependencies.items()
    }
    referrers = defaultdict(set)
    for source, targets in remaining.items():
        for target in targets:
            referrers[target].add(source)
    ready = deque(sorted(identity for identity, targets in remaining.items() if not targets))
    result = []
    while ready:
        identity = ready.popleft()
        result.append(identity)
        for referrer in sorted(referrers[identity]):
            remaining[referrer].discard(identity)
            if not remaining[referrer]:
                ready.append(referrer)
        ready = deque(sorted(ready))
    if len(result) != len(remaining):
        raise TenantDumpDependencyError("Lane D row dependency planning did not close.")
    return result


def _cyclic_components(graph):
    index = 0
    indices = {}
    lowlinks = {}
    stack = []
    on_stack = set()
    components = []

    def visit(node):
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component = set()
        while True:
            item = stack.pop()
            on_stack.remove(item)
            component.add(item)
            if item == node:
                break
        if len(component) > 1 or node in graph[node]:
            components.append(component)

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return components


def model_dependency_order(models):
    """Deterministic SCC-collapsed model order for deletion and diagnostics."""
    by_label = {model._meta.label: model for model in models}
    graph = {label: set() for label in by_label}
    for label, model in by_label.items():
        for field in model._meta.concrete_fields:
            if field.is_relation and field.related_model is not None:
                target = field.related_model._meta.label
                if target in by_label and target != label:
                    graph[label].add(target)
    components = _all_components(graph)
    owner = {node: index for index, component in enumerate(components) for node in component}
    component_graph = {index: set() for index in range(len(components))}
    for source, targets in graph.items():
        for target in targets:
            if owner[source] != owner[target]:
                component_graph[owner[source]].add(owner[target])
    component_order = _topological_order(component_graph, set())
    return tuple(
        by_label[label]
        for component_index in component_order
        for label in sorted(components[component_index])
    )


def _all_components(graph):
    cyclic = _cyclic_components(graph)
    claimed = set().union(*cyclic) if cyclic else set()
    return [*cyclic, *({node} for node in sorted(set(graph) - claimed))]
