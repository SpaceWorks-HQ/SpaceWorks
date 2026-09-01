import pytest
from django.db import models
from django.test.utils import isolate_apps

from apps.tenant_migration.tenant_dump_errors import TenantDumpDependencyError
from apps.tenant_migration.tenant_dump_graph import plan_row_load
from apps.tenant_migration.tenant_dump_raw import SanitizedRow


@isolate_apps()
def test_genuine_nullable_cycle_uses_two_pass_only_for_cycle_edges():
    class Left(models.Model):
        right = models.ForeignKey(
            "Right", null=True, on_delete=models.PROTECT, related_name="+"
        )

        class Meta:
            app_label = "lane_d_cycle_fixture"

    class Right(models.Model):
        left = models.ForeignKey(
            Left, null=True, on_delete=models.PROTECT, related_name="+"
        )

        class Meta:
            app_label = "lane_d_cycle_fixture"

    rows = [
        SanitizedRow(Left, 1, {"id": 1, "right_id": 2}),
        SanitizedRow(Right, 2, {"id": 2, "left_id": 1}),
    ]

    plan = plan_row_load(rows)

    assert plan.used_two_pass is True
    assert {(item.identity, item.column, item.value) for item in plan.deferred_foreign_keys} == {
        (("lane_d_cycle_fixture.Left", 1), "right_id", 2),
        (("lane_d_cycle_fixture.Right", 2), "left_id", 1),
    }
    assert all(
        row.values[next(iter({"right_id", "left_id"} & set(row.values)))] is None
        for row in plan.rows
    )


@isolate_apps()
def test_acyclic_nullable_fk_does_not_use_two_pass_and_orders_parent_first():
    class Parent(models.Model):
        class Meta:
            app_label = "lane_d_cycle_fixture"

    class Child(models.Model):
        parent = models.ForeignKey(Parent, null=True, on_delete=models.PROTECT)

        class Meta:
            app_label = "lane_d_cycle_fixture"

    plan = plan_row_load(
        [
            SanitizedRow(Child, 2, {"id": 2, "parent_id": 1}),
            SanitizedRow(Parent, 1, {"id": 1}),
        ]
    )

    assert plan.used_two_pass is False
    assert [row.model._meta.label for row in plan.rows] == [
        "lane_d_cycle_fixture.Parent",
        "lane_d_cycle_fixture.Child",
    ]


@isolate_apps()
def test_non_nullable_cycle_refuses_instead_of_disabling_constraints():
    class Left(models.Model):
        right = models.ForeignKey("Right", on_delete=models.PROTECT)

        class Meta:
            app_label = "lane_d_cycle_fixture"

    class Right(models.Model):
        left = models.ForeignKey(Left, null=True, on_delete=models.PROTECT)

        class Meta:
            app_label = "lane_d_cycle_fixture"

    with pytest.raises(TenantDumpDependencyError, match="non-nullable FK cycle"):
        plan_row_load(
            [
                SanitizedRow(Left, 1, {"id": 1, "right_id": 2}),
                SanitizedRow(Right, 2, {"id": 2, "left_id": 1}),
            ]
        )
