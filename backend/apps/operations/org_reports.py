"""Organization report orchestration: breakdown and combined total are inseparable."""

from decimal import Decimal

from apps.operations.org_report_aggregate import aggregate_rows
from apps.operations.org_report_identity import (
    distinct_member_activity,
    globally_ranked_borrowers,
)
from apps.operations.org_report_strategies import STRATEGIES, organization_strategy
from apps.operations.report_registry import ReportDefinition, ReportResult
from apps.operations.report_scope import ReportScope, ReportScopeMode


class OrganizationAggregationError(ValueError):
    """A typed organization aggregation boundary failure."""


class InvalidOrganizationAggregationScope(OrganizationAggregationError):
    """Organization totals may only consume a server-resolved COMBINED scope."""


def organization_strategy_keys():
    return tuple(STRATEGIES)


def organization_report_data(
    definition: ReportDefinition,
    scope: ReportScope,
    *,
    limit: int,
    date_range=None,
    report_filters=None,
):
    _validate_inputs(definition, scope, limit)
    strategy = organization_strategy(definition.key)
    if not scope.makerspace_ids:
        return _payload(definition.key, strategy.kind.value, [], [])

    rows_by_space = []
    breakdown = []
    for makerspace_id in scope.makerspace_ids:
        result = definition.builder()(
            makerspace_id,
            limit=None,
            date_range=date_range,
            **(report_filters or {}),
        )
        rows = _result_rows(result)
        rows_by_space.append((makerspace_id, rows))
        breakdown.append({
            "makerspace_id": makerspace_id,
            "rows": [_public_row(row, definition, strategy) for row in rows[:limit]],
        })

    if definition.key == "top-borrowers":
        total = globally_ranked_borrowers(
            scope, date_range=date_range, limit=limit
        )
    elif definition.key == "member-activity":
        total = distinct_member_activity(scope, date_range=date_range)
    else:
        total = aggregate_rows(definition.key, rows_by_space, limit=limit)
    total = [_project(row, strategy.total_fields) for row in total]
    return _payload(
        definition.key,
        strategy.kind.value,
        breakdown,
        total,
    )


# Stage 4 [P2]: the per-space loop below runs one builder call per owned makerspace, so
# query count grows linearly with the scope. Bounding the scope keeps that cost, and the
# memory of unbounded row sets, predictable rather than unbounded.
#
# Note limit=None in that loop is REQUIRED, not an oversight: SUM/GROUP_SUM/WEIGHTED_RATE
# totals must see every row, so pushing the caller's limit down would silently produce a
# wrong total. Per-space runs for the BREAKDOWN are the owner's approved hybrid decision.
#
# The real fix -- scope-aware batched queries or database aggregates, which would also
# satisfy the no-N+1 reporting rule in docs/INVARIANTS.md properly -- means changing every
# analytics builder's signature and is deliberately NOT smuggled in here. Filed as
# follow-up work.
MAX_ORGANIZATION_SCOPE_SPACES = 25


def _validate_inputs(definition, scope, limit):
    if not isinstance(definition, ReportDefinition):
        raise TypeError("definition must be a ReportDefinition.")
    if not isinstance(scope, ReportScope):
        raise TypeError("scope must be a ReportScope.")
    if scope.mode is not ReportScopeMode.COMBINED:
        raise InvalidOrganizationAggregationScope(
            "Only a COMBINED report scope may flatten organization rows."
        )
    if len(scope.makerspace_ids) > MAX_ORGANIZATION_SCOPE_SPACES:
        raise InvalidOrganizationAggregationScope(
            "This organization owns more makerspaces than one aggregate request may "
            f"span ({len(scope.makerspace_ids)} > {MAX_ORGANIZATION_SCOPE_SPACES}). "
            "Narrow the request or wait for scope-batched aggregates."
        )
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise OrganizationAggregationError("limit must be a positive integer.")
    strategy = organization_strategy(definition.key)
    if not definition.summary:
        declared_fields = set(strategy.total_fields) | set(
            strategy.breakdown_only_fields
        )
        if declared_fields != set(definition.fields):
            raise OrganizationAggregationError(
                f"Strategy fields for {definition.key!r} do not match its report definition."
            )


def _result_rows(result):
    if isinstance(result, ReportResult):
        return [dict(record) for record in result.records]
    if isinstance(result, dict):
        return [dict(result)]
    if not isinstance(result, list) or not result:
        return []
    header = result[0]
    if not isinstance(header, list):
        raise OrganizationAggregationError("Report builder returned an invalid row matrix.")
    return [dict(zip(header, row, strict=True)) for row in result[1:]]


def _public_row(row, definition, strategy):
    fields = strategy.total_fields if definition.summary else definition.fields
    return _project(row, fields)


def _project(row, fields):
    return {field: _json_value(row.get(field)) for field in fields}


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.01")), ".2f")
    return value


def _payload(report_key, strategy, breakdown, total):
    return {
        "report_key": report_key,
        "strategy": strategy,
        "breakdown": breakdown,
        "total": {"rows": total},
    }
