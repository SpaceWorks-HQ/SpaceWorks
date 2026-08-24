"""Fail-closed validation for the committed Compose pointer wrapper."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from .host_pointer import POINTER_KEYS, read_pointer


class TopologyRecordError(RuntimeError):
    pass


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assignments(path):
    result = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            raise TopologyRecordError("Static environment contains an invalid line.")
        key, value = line.split("=", 1)
        if key in result:
            raise TopologyRecordError(f"Static environment repeats {key}.")
        result[key] = value
    return result


def configuration_facts(*, topology, static_env, compose_files):
    assignments = _assignments(static_env)
    duplicate = set(POINTER_KEYS) & set(assignments)
    if duplicate:
        raise TopologyRecordError(
            "Static environment duplicates database pointer assignment(s): "
            + ", ".join(sorted(duplicate))
        )
    scheduler_mode = assignments.get("SPACEWORKS_SCHEDULER_MODE")
    if scheduler_mode not in {"image", "external"}:
        raise TopologyRecordError("Static environment has no declared scheduler mode.")
    return {
        "version": 1,
        "topology": topology,
        "scheduler_mode": scheduler_mode,
        "static_environment_sha256": _sha256(static_env),
        "compose_files": [
            {"path": Path(path).name, "sha256": _sha256(path)}
            for path in compose_files
        ],
    }


def write_topology_record(path, facts):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing_stat = target.stat(follow_symlinks=False) if target.exists() else None
    temporary = target.with_name(f".{target.name}.tmp")
    payload = json.dumps(facts, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600,
        )
        if existing_stat is not None:
            os.fchown(fd, existing_stat.st_uid, existing_stat.st_gid)
            os.fchmod(fd, stat.S_IMODE(existing_stat.st_mode))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def validate_compose_wrapper(
    *,
    topology,
    static_env,
    pointer_file,
    topology_record,
    compose_files,
    require_root_owned=True,
):
    read_pointer(pointer_file, require_root_owned=require_root_owned)
    paths = [Path(static_env), Path(topology_record), *(Path(item) for item in compose_files)]
    try:
        if require_root_owned:
            static_stat = paths[0].stat(follow_symlinks=False)
            record_stat = paths[1].stat(follow_symlinks=False)
            if (
                static_stat.st_uid not in {0, __import__("os").geteuid()}
                or static_stat.st_mode & 0o077
                or record_stat.st_uid != 0
                or record_stat.st_mode & 0o027
                or not all(stat.S_ISREG(item.st_mode) for item in (static_stat, record_stat))
            ):
                raise TopologyRecordError("Compose wrapper input is misowned.")
        stored = json.loads(Path(topology_record).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TopologyRecordError("Topology record is missing or unreadable.") from exc
    actual = configuration_facts(
        topology=topology,
        static_env=static_env,
        compose_files=compose_files,
    )
    if stored != actual:
        raise TopologyRecordError("Compose configuration digest drifted.")
    return actual
