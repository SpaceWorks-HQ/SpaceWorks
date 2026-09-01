"""Fsynced append-only effect ledger for resumable host operations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid


SHA256 = re.compile(r"^[0-9a-f]{64}$")
DATABASE_RESTORE_PHASE = "database-restore"


class RunLedgerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    phase: str | None
    attempt: int
    requires_new_empty_sibling: bool


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RunLedger:
    def __init__(self, path, *, run_id, artifact_sha256):
        self.path = Path(path)
        try:
            self.run_id = str(uuid.UUID(str(run_id)))
        except ValueError as exc:
            raise RunLedgerError("Run ID is invalid.") from exc
        if not isinstance(artifact_sha256, str) or not SHA256.fullmatch(artifact_sha256):
            raise RunLedgerError("Artifact digest is invalid.")
        self.artifact_sha256 = artifact_sha256

    def records(self):
        if not self.path.exists():
            return []
        result = []
        try:
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    record = json.loads(line)
                    self._validate_record(record)
                    result.append(record)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RunLedgerError("Run ledger is unreadable or malformed.") from exc
        begun = {}
        done_phases = set()
        attempts = {}
        for record in result:
            key = (record["phase"], record["attempt"])
            if record["state"] == "begun":
                expected_attempt = attempts.get(record["phase"], 0) + 1
                if (
                    key in begun
                    or record["phase"] in done_phases
                    or record["attempt"] != expected_attempt
                ):
                    raise RunLedgerError("Run ledger attempt ordering is invalid.")
                begun[key] = record
                attempts[record["phase"]] = record["attempt"]
            elif key not in begun or record["phase"] in done_phases:
                raise RunLedgerError("Run ledger completes an effect that never began.")
            else:
                done_phases.add(record["phase"])
        return result

    def resume_decision(self, phases):
        records = self.records()
        phases = tuple(phases)
        if not phases or len(set(phases)) != len(phases):
            raise RunLedgerError("Run phases must be a non-empty unique sequence.")
        unknown = {item["phase"] for item in records} - set(phases)
        if unknown:
            raise RunLedgerError("Run ledger contains an undeclared phase.")
        for phase in phases:
            phase_records = [item for item in records if item["phase"] == phase]
            if any(item["state"] == "done" for item in phase_records):
                continue
            begun = [item for item in phase_records if item["state"] == "begun"]
            return ResumeDecision(
                phase=phase,
                attempt=len(begun) + 1,
                requires_new_empty_sibling=(phase == DATABASE_RESTORE_PHASE and bool(begun)),
            )
        return ResumeDecision(None, 0, False)

    def begin(self, phase, detail):
        records = self.records()
        if any(item["phase"] == phase and item["state"] == "done" for item in records):
            raise RunLedgerError("Completed run phase cannot be repeated.")
        phase_begun = [
            item for item in records
            if item["phase"] == phase and item["state"] == "begun"
        ]
        if phase == DATABASE_RESTORE_PHASE and phase_begun:
            sibling = detail.get("sibling") if isinstance(detail, dict) else None
            prior = phase_begun[-1]["detail"].get("sibling")
            if (
                not isinstance(sibling, dict)
                or sibling.get("empty") is not True
                or not sibling.get("identity")
                or sibling.get("identity") == (prior or {}).get("identity")
            ):
                raise RunLedgerError(
                    "An interrupted database restore requires a new empty sibling."
                )
        started_at = _now()
        record = self._record(
            phase=phase,
            state="begun",
            attempt=len(phase_begun) + 1,
            started_at=started_at,
            finished_at=None,
            detail=detail,
        )
        self._append(record)
        return record

    def finish(self, begun, detail=None):
        self._validate_record(begun)
        if begun["state"] != "begun":
            raise RunLedgerError("Only a begun effect can be completed.")
        records = self.records()
        matching = [
            item for item in records
            if item["phase"] == begun["phase"]
            and item["attempt"] == begun["attempt"]
            and item["state"] == "begun"
        ]
        if len(matching) != 1 or matching[0] != begun:
            raise RunLedgerError("Effect completion does not match its begun record.")
        if any(
            item["phase"] == begun["phase"]
            and item["attempt"] == begun["attempt"]
            and item["state"] == "done"
            for item in records
        ):
            raise RunLedgerError("Effect attempt is already complete.")
        record = self._record(
            phase=begun["phase"],
            state="done",
            attempt=begun["attempt"],
            started_at=begun["started_at"],
            finished_at=_now(),
            detail=begun["detail"] if detail is None else detail,
        )
        self._append(record)
        return record

    @contextmanager
    def effect(self, phase, detail):
        begun = self.begin(phase, detail)
        yield begun
        self.finish(begun)

    def _record(self, **values):
        return {
            "run_id": self.run_id,
            "artifact_sha256": self.artifact_sha256,
            **values,
        }

    def _append(self, record):
        self._validate_record(record)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        existed = self.path.exists()
        fd = os.open(
            self.path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
            0o600,
        )
        try:
            payload = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            encoded = payload.encode("utf-8")
            written = 0
            while written < len(encoded):
                written += os.write(fd, encoded[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
        if not existed:
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def _validate_record(self, record):
        required = {
            "run_id", "artifact_sha256", "phase", "state", "attempt",
            "started_at", "finished_at", "detail",
        }
        if not isinstance(record, dict) or set(record) != required:
            raise RunLedgerError("Run ledger record has an invalid shape.")
        if record["run_id"] != self.run_id or record["artifact_sha256"] != self.artifact_sha256:
            raise RunLedgerError("Run ledger identity mismatch.")
        if record["state"] not in {"begun", "done"}:
            raise RunLedgerError("Run ledger state is invalid.")
        if not isinstance(record["phase"], str) or not record["phase"]:
            raise RunLedgerError("Run ledger phase is invalid.")
        if isinstance(record["attempt"], bool) or not isinstance(record["attempt"], int) or record["attempt"] < 1:
            raise RunLedgerError("Run ledger attempt is invalid.")
        if record["state"] == "begun" and record["finished_at"] is not None:
            raise RunLedgerError("A begun ledger effect cannot be finished.")
        if record["state"] == "done" and not isinstance(record["finished_at"], str):
            raise RunLedgerError("A done ledger effect needs a finish timestamp.")
        if not isinstance(record["started_at"], str) or not isinstance(record["detail"], dict):
            raise RunLedgerError("Run ledger timestamps or detail are invalid.")
        try:
            started = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
            finished = (
                datetime.fromisoformat(record["finished_at"].replace("Z", "+00:00"))
                if record["finished_at"] else None
            )
        except ValueError as exc:
            raise RunLedgerError("Run ledger timestamp is malformed.") from exc
        if started.tzinfo is None or (finished is not None and (
            finished.tzinfo is None or finished < started
        )):
            raise RunLedgerError("Run ledger timestamp ordering is invalid.")
