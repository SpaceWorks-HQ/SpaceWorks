"""Fail-closed scheduler declaration checks for host-orchestrated topologies."""


class TopologyConfigurationError(RuntimeError):
    pass


def validate_scheduler_contract(document):
    contract = document.get("x-spaceworks-host-orchestration")
    if not isinstance(contract, dict):
        raise TopologyConfigurationError("Topology has no host-orchestration declaration.")
    scheduler = contract.get("scheduler")
    if not isinstance(scheduler, dict):
        raise TopologyConfigurationError("Topology has no scheduler declaration.")
    mode = scheduler.get("mode")
    if mode == "image":
        services = scheduler.get("services")
        declared = document.get("services") or {}
        if not isinstance(services, list) or not services or any(
            service not in declared for service in services
        ):
            raise TopologyConfigurationError("Image scheduler services are incomplete.")
        return scheduler
    if mode == "external":
        host_gate = scheduler.get("host_gate_command")
        disablement = scheduler.get("control_plane_disablement")
        if not any(isinstance(value, str) and value.strip() for value in (host_gate, disablement)):
            raise TopologyConfigurationError(
                "External scheduler declares neither the host gate nor control-plane disablement."
            )
        return scheduler
    raise TopologyConfigurationError("Scheduler mode must be image or external.")


def validate_scheduler_environment(environ):
    mode = environ.get("SPACEWORKS_SCHEDULER_MODE", "")
    if mode == "image":
        services = [item.strip() for item in environ.get(
            "SPACEWORKS_SCHEDULER_SERVICES", ""
        ).split(",") if item.strip()]
        if not services:
            raise TopologyConfigurationError("Image scheduler service declaration is empty.")
        return mode
    if mode == "external" and any(
        environ.get(name, "").strip()
        for name in (
            "SPACEWORKS_SCHEDULER_HOST_GATE_COMMAND",
            "SPACEWORKS_SCHEDULER_CONTROL_PLANE_DISABLEMENT",
        )
    ):
        return mode
    raise TopologyConfigurationError(
        "Scheduler mode is missing or external scheduler has no independent fence."
    )


def validate_host_orchestration_contract(document):
    scheduler = validate_scheduler_contract(document)
    contract = document["x-spaceworks-host-orchestration"]
    pointer = contract.get("pointer")
    if not isinstance(pointer, dict) or set(pointer) != {
        "mode", "path", "static_environment"
    }:
        raise TopologyConfigurationError("Topology pointer declaration is incomplete.")
    if pointer["mode"] != "atomic-file" or pointer["path"] != (
        "/var/lib/spaceworks/ops/database-pointer.env"
    ):
        raise TopologyConfigurationError("Compose topology lacks the atomic ops pointer.")
    if contract.get("database_identity") != "endpoint-plus-queried-uuid":
        raise TopologyConfigurationError("Topology lacks an authoritative identity query.")
    lifecycle = contract.get("sibling_lifecycle")
    if lifecycle not in {"bundled-owned-database", "provider-isolated-database"}:
        raise TopologyConfigurationError("Topology lacks a safe sibling lifecycle.")
    writers = contract.get("writer_services")
    declared_services = document.get("services") or {}
    if not isinstance(writers, list) or not writers or any(
        writer not in declared_services for writer in writers
    ):
        raise TopologyConfigurationError("Topology writer rollout is incomplete.")
    discovered_writers = set()
    for name, service in declared_services.items():
        command = service.get("command") if isinstance(service, dict) else None
        if (
            isinstance(command, list)
            and len(command) >= 2
            and command[0] == "--role"
            and command[1] in {"backend", "worker", "beat", "cron"}
            and name != "candidate-backend"
        ):
            discovered_writers.add(name)
    if set(writers) != discovered_writers:
        raise TopologyConfigurationError(
            "Topology writer rollout does not equal the ordinary image writer set."
        )
    expected_scheduler_writers = set(scheduler.get("services") or ())
    if scheduler["mode"] == "image" and not expected_scheduler_writers <= set(writers):
        raise TopologyConfigurationError("Topology omits an image scheduler writer.")
    return contract
