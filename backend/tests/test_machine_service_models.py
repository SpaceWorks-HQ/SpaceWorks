from importlib import import_module

import pytest
from django.core.exceptions import ValidationError
from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.utils import timezone

from apps.makerspaces import limits
from apps.makerspaces import lifecycle
from apps.makerspaces.models import DEFAULT_ENABLED_MODULES, Makerspace
from apps.makerspaces.module_profiles import EVERYTHING, profile_modules
from apps.makerspaces.platform import MODULE_WORKFLOWS, bootstrap_payload
from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.machines.models import (
    Machine,
    MachineConsumable,
    MachineServiceRequest,
    MachineType,
    ServiceBucket,
    ServiceRequestConsumption,
    ServiceRequestFile,
    get_or_create_default_bucket,
)
from tests.return_helpers import make_product, make_space, make_user


pytestmark = pytest.mark.django_db
migration = import_module("apps.makerspaces.migrations.0040_machine_service_module")


def make_machine(makerspace, name="Service machine"):
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug=f"service-{makerspace.id}-{name}", name="Service type"
    )
    return Machine.objects.create(makerspace=makerspace, machine_type=machine_type, name=name)


def make_request(makerspace, machine=None):
    machine = machine or make_machine(makerspace)
    bucket = ServiceBucket.objects.create(machine=machine, name="Service")
    user = make_user(f"service-requester-{makerspace.id}-{machine.id}")
    return MachineServiceRequest.objects.create(bucket=bucket, requester=user, title="Repair it")


def test_schema_constraints_indexes_and_default_machine_assignment():
    makerspace = make_space("service-model-schema")
    request = make_request(makerspace)
    assert request.assigned_machine_id == request.bucket.machine_id
    names = connection.introspection.get_constraints(connection.cursor(), MachineServiceRequest._meta.db_table)
    for name in (
        "service_req_est_minutes_nonnegative",
        "service_req_actual_minutes_nonnegative",
        "service_req_fail_percent_range",
        "servicereq_requester_created_idx",
        "servicereq_bucket_status_idx",
        "servicereq_machine_status_idx",
        "servicereq_completed_idx",
        "servicereq_failed_idx",
    ):
        assert name in names

    for field, value in (("estimated_minutes", -1), ("actual_minutes", -1), ("fail_percent_complete", 101)):
        with pytest.raises(IntegrityError), transaction.atomic():
            MachineServiceRequest.objects.filter(pk=request.pk).update(**{field: value})


def test_unique_bucket_token_and_consumption_constraints():
    makerspace = make_space("service-model-uniques")
    request = make_request(makerspace)
    with pytest.raises(IntegrityError), transaction.atomic():
        ServiceBucket.objects.create(machine=request.bucket.machine, name="Service")
    with pytest.raises(IntegrityError), transaction.atomic():
        MachineServiceRequest.objects.create(
            bucket=request.bucket, requester=request.requester, title="Duplicate token",
            public_token=request.public_token,
        )

    product = make_product(makerspace, name="Consumable")
    consumable = MachineConsumable.objects.create(
        machine=request.bucket.machine, measurement="count", product=product
    )
    ServiceRequestConsumption.objects.create(
        service_request=request, machine_consumable=consumable, measurement="count",
        product=product, quantity="1", outcome="completed",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ServiceRequestConsumption.objects.create(
            service_request=request, machine_consumable=consumable, measurement="count",
            product=product, quantity="1", outcome="completed",
        )


def test_consumption_is_append_only_and_attached_file_metadata_is_immutable():
    makerspace = make_space("service-model-immutable")
    request = make_request(makerspace)
    product = make_product(makerspace, name="Service product")
    consumable = MachineConsumable.objects.create(
        machine=request.bucket.machine, measurement="count", product=product
    )
    consumption = ServiceRequestConsumption.objects.create(
        service_request=request, machine_consumable=consumable, measurement="count",
        product=product, quantity="1", outcome="completed",
    )
    with pytest.raises(RuntimeError, match="append-only"):
        ServiceRequestConsumption.objects.filter(pk=consumption.pk).update(quantity="2")
    with pytest.raises(RuntimeError, match="append-only"):
        ServiceRequestConsumption.objects.filter(pk=consumption.pk).delete()

    file = ServiceRequestFile.objects.create(
        machine=request.bucket.machine, kind="attachment", object_key="service/a", owner_user_id=request.requester_id,
        content_type="application/pdf", original_filename="before.pdf", size_bytes=10, attached_at=timezone.now(),
    )
    file.object_key = "service/b"
    with pytest.raises(RuntimeError, match="immutable"):
        file.save()

    with pytest.raises(Exception, match="append-only/immutable"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE machines_servicerequestconsumption SET quantity = 2 WHERE id = %s",
                [consumption.id],
            )


def test_purge_collects_service_request_private_object_keys():
    makerspace = make_space("service-purge-keys")
    request = make_request(makerspace)
    file = ServiceRequestFile.objects.create(
        machine=request.bucket.machine, kind="attachment", object_key="service/private.pdf",
        owner_user_id=request.requester_id,
    )
    assert file.object_key in lifecycle._collect_storage_keys(makerspace)


def test_default_bucket_is_idempotent_and_rejects_ineligible_machines():
    makerspace = make_space("service-default-bucket")
    machine = make_machine(makerspace)
    first = get_or_create_default_bucket(machine)
    second = get_or_create_default_bucket(machine)
    assert first.pk == second.pk
    assert first.name == "Service Requests"
    assert first.is_active is True
    assert ServiceBucket.objects.filter(machine=machine, name="Service Requests").count() == 1

    machine.status = Machine.Status.RUNNING
    machine.save(update_fields=["status"])
    with pytest.raises(Exception, match="active idle"):
        get_or_create_default_bucket(machine)
    machine.status, machine.is_active = Machine.Status.IDLE, False
    machine.save(update_fields=["status", "is_active"])
    with pytest.raises(Exception, match="active idle"):
        get_or_create_default_bucket(machine)
    other = make_space("service-default-bucket-other")
    machine.is_active = True
    machine.save(update_fields=["is_active"])
    with pytest.raises(Exception, match="active idle"):
        get_or_create_default_bucket(machine, makerspace=other)


def test_module_migration_default_workflow_and_valid_disable():
    makerspace = make_space("service-module-migration")
    makerspace.enabled_modules = ["custom", "machines"]
    makerspace.save(update_fields=["enabled_modules"])
    migration.enable_machine_service(apps, None)
    migration.enable_machine_service(apps, None)
    makerspace.refresh_from_db()
    assert makerspace.enabled_modules == ["custom", "machines", "machine_service"]
    migration.disable_machine_service(apps, None)
    makerspace.refresh_from_db()
    assert makerspace.enabled_modules == ["custom", "machines"]
    # Opt-in: installable rather than on by default.
    assert "machine_service" not in DEFAULT_ENABLED_MODULES
    assert "machine_service" in profile_modules(EVERYTHING)
    assert MODULE_WORKFLOWS["machine_service"] == ["machine_service_requests"]
    assert "machine_service" in bootstrap_payload(make_space("service-module-default"))["modules"]
    serializer = MakerspaceSerializer(
        makerspace,
        data={"enabled_modules": ["machines"]},
        partial=True,
    )
    assert serializer.is_valid(), serializer.errors


def test_printing_module_requires_machine_service():
    makerspace = make_space("printing-requires-machine-service")
    makerspace.enabled_modules = ["printing"]

    with pytest.raises(ValidationError, match="Printing requires machine service"):
        makerspace.full_clean()

    serializer = MakerspaceSerializer(
        makerspace,
        data={"enabled_modules": ["printing"]},
        partial=True,
    )
    assert not serializer.is_valid()
    assert "enabled_modules" in serializer.errors


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
def test_managed_service_limits_have_defaults_and_validate():
    makerspace = make_space("service-managed-limits")
    assert limits.resource_limit(makerspace, "machine_service_open") == 100
    assert limits.resource_limit(makerspace, "machine_service_submit") == 100
    values = {"machine_service_open": 1, "machine_service_submit": 2}
    assert limits.validate_resource_limit_overrides(values) == values


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_self_host_service_limits_are_dormant():
    makerspace = make_space("service-self-host-limits")
    assert limits.resource_limit(makerspace, "machine_service_open") is None
    assert limits.resource_limit(makerspace, "machine_service_submit") is None


@pytest.mark.django_db(transaction=True)
def test_machine_service_migrations_upgrade_from_real_heads():
    from_target = [("machines", "0007_machine_usage_time_index"), ("makerspaces", "0039_seed_and_backfill_roles")]
    target = [("machines", "0008_machine_service_requests"), ("makerspaces", "0040_machine_service_module")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        OldMakerspace = old_apps.get_model("makerspaces", "Makerspace")
        OldMachineType = old_apps.get_model("machines", "MachineType")
        OldMachine = old_apps.get_model("machines", "Machine")
        makerspace = OldMakerspace.objects.create(
            name="Migration service", slug="migration-service", enabled_modules=["machines"]
        )
        machine_type = OldMachineType.objects.create(
            makerspace_id=makerspace.id, slug="migration-service", name="Migration service"
        )
        OldMachine.objects.create(makerspace_id=makerspace.id, machine_type_id=machine_type.id, name="Migrated")

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        NewMakerspace = new_apps.get_model("makerspaces", "Makerspace")
        assert new_apps.get_model("machines", "MachineServiceRequest").objects.count() == 0
        assert new_apps.get_model("machines", "ServiceBucket").objects.count() == 0
        assert "machine_service" in NewMakerspace.objects.get(pk=makerspace.id).enabled_modules
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
