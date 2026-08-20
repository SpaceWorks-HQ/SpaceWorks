from dataclasses import FrozenInstanceError

import pytest

from apps.makerspaces.models import Makerspace
from apps.operations import report_scope
from apps.operations.report_scope import (
    ReportScope,
    ReportScopeMode,
    combined_report_scope,
    deployment_report_scope,
    single_report_scope,
)


pytestmark = pytest.mark.django_db


def test_report_scope_factories_make_grouping_explicit_and_keep_scoped_ids_compatible():
    makerspace = Makerspace.objects.create(
        name="Typed Report Scope",
        slug="typed-report-scope",
    )

    assert tuple(ReportScopeMode) == (
        ReportScopeMode.SINGLE,
        ReportScopeMode.BY_MAKERSPACE,
        ReportScopeMode.COMBINED,
    )
    single = single_report_scope(makerspace)
    assert single.makerspace_ids == (makerspace.id,)
    assert single.mode is ReportScopeMode.SINGLE
    assert deployment_report_scope().mode is ReportScopeMode.BY_MAKERSPACE
    assert report_scope.scoped_ids([11, 22]) == [[11, 22]]


def test_report_scope_constructor_is_private_and_instances_are_frozen():
    scope = combined_report_scope(Makerspace.objects.none())

    with pytest.raises(TypeError):
        ReportScope((1,), ReportScopeMode.COMBINED)
    with pytest.raises(FrozenInstanceError):
        scope.mode = ReportScopeMode.SINGLE
    with pytest.raises(TypeError):
        combined_report_scope([])
