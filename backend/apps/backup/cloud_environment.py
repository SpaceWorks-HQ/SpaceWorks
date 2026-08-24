"""One-time Cloud Compose initialization from the invoking environment."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

import yaml

from .host_private_file import write_private_file_fsynced
from .host_pointer import POINTER_KEYS, PointerRecord, write_pointer_atomic
from .host_topology_record import configuration_facts, write_topology_record
from .topology import validate_host_orchestration_contract


REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-+?])(.*?))?\}")


class CloudEnvironmentError(RuntimeError):
    pass


def referenced_variables(compose_path):
    text = Path(compose_path).read_text(encoding="utf-8")
    return tuple(sorted({match.group(1) for match in REFERENCE.finditer(text)}))


def _resolve(match, environ):
    name, operator, argument = match.groups()
    present = name in environ
    value = environ.get(name, "")
    if operator in {":?", "?"} and (not present or (operator == ":?" and not value)):
        raise CloudEnvironmentError(f"Required Cloud variable is missing: {name}.")
    if operator in {":-", "-"} and (not present or (operator == ":-" and not value)):
        return argument
    if operator in {":+", "+"}:
        return argument if present and (operator == "+" or value) else ""
    return value


def effective_variables(compose_path, environ):
    text = Path(compose_path).read_text(encoding="utf-8")
    resolved = {}
    for match in REFERENCE.finditer(text):
        name = match.group(1)
        value = _resolve(match, environ)
        prior = resolved.setdefault(name, value)
        if prior != value:
            raise CloudEnvironmentError(
                f"Cloud variable {name} resolves inconsistently in Compose."
            )
    return resolved


def _dotenv_line(name, value):
    if not isinstance(value, str) or any(character in value for character in "\x00\r\n"):
        raise CloudEnvironmentError(f"Cloud variable {name} cannot be encoded safely.")
    if re.fullmatch(r"[A-Za-z0-9_./:@,+-]*", value):
        return f"{name}={value}\n"
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"{name}='{escaped}'\n"


def _inventory(values):
    return [
        {
            "name": name,
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "present": True,
        }
        for name, value in sorted(values.items())
    ]


def _rendered_writer_database_urls(rendered, writer_services):
    try:
        document = yaml.safe_load(rendered)
    except yaml.YAMLError as exc:
        raise CloudEnvironmentError("Scrubbed Cloud Compose output is malformed.") from exc
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        return ()
    found = []
    for name in writer_services:
        service = services.get(name)
        environment = service.get("environment") if isinstance(service, dict) else None
        if isinstance(environment, dict):
            found.append(environment.get(POINTER_KEYS[0]))
        elif isinstance(environment, list):
            prefix = POINTER_KEYS[0] + "="
            matches = [
                item[len(prefix):] for item in environment
                if isinstance(item, str) and item.startswith(prefix)
            ]
            found.append(matches[0] if len(matches) == 1 else None)
        else:
            found.append(None)
    return tuple(found)


def init_from_current_environment(
    *, compose_path, static_env_path, pointer_path, topology_record_path,
    compose_renderer, environ=None, require_root_owned=True,
):
    """Capture values once and validate output rendered by the host orchestrator."""
    environ = dict(os.environ if environ is None else environ)
    compose_path = Path(compose_path)
    with compose_path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    contract = validate_host_orchestration_contract(document)
    # Generation 1 is the protocol-defined initialization value, not an ambient
    # deployment input. The effective database URL still must come from this invocation.
    environ[POINTER_KEYS[1]] = "1"
    values = effective_variables(compose_path, environ)
    try:
        database_url = values.pop(POINTER_KEYS[0])
    except KeyError as exc:
        raise CloudEnvironmentError("Cloud Compose does not declare DATABASE_URL.") from exc
    if values.pop(POINTER_KEYS[1], None) != "1":
        raise CloudEnvironmentError("Cloud pointer initialization generation is invalid.")
    scheduler = contract["scheduler"]
    values["SPACEWORKS_SCHEDULER_MODE"] = scheduler["mode"]
    if scheduler["mode"] == "image":
        values["SPACEWORKS_SCHEDULER_SERVICES"] = ",".join(scheduler["services"])
    static_payload = "".join(_dotenv_line(name, value) for name, value in sorted(values.items()))
    write_private_file_fsynced(
        static_env_path,
        static_payload,
        require_root_owned=require_root_owned,
    )
    write_pointer_atomic(
        pointer_path,
        PointerRecord(database_url, 1),
        require_root_owned=require_root_owned,
    )
    facts = configuration_facts(
        topology="cloud", static_env=static_env_path, compose_files=[compose_path]
    )
    write_topology_record(topology_record_path, facts)
    try:
        rendered = compose_renderer(compose_path, static_env_path, pointer_path)
    except Exception as exc:
        raise CloudEnvironmentError(
            "Cloud Compose config cannot be reproduced under a scrubbed environment."
        ) from exc
    rendered_urls = _rendered_writer_database_urls(
        rendered, contract["writer_services"]
    )
    if not rendered_urls or any(value != database_url for value in rendered_urls):
        raise CloudEnvironmentError(
            "Scrubbed Cloud Compose config does not reproduce the database URL."
        )
    return {
        "variables": _inventory({
            **values, POINTER_KEYS[0]: database_url, POINTER_KEYS[1]: "1",
        }),
        "static_environment_sha256": facts["static_environment_sha256"],
        "compose_sha256": facts["compose_files"][0]["sha256"],
        "pointer_generation": 1,
        "scheduler_mode": scheduler["mode"],
        "rendered_config_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }
