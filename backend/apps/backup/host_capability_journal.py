"""Root-owned, fsynced, append-only nonce journal."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat

from .host_capability_types import (
    CapabilityError,
    canonical_json,
    timestamp,
    timestamp_text,
    utc_now,
    validate_record,
    validate_request,
)


class CapabilityJournal:
    def __init__(self, path, *, require_root_owned=True):
        self.path = Path(path)
        self.require_root_owned = require_root_owned

    def arm(self, record):
        record = validate_record(record.payload() if hasattr(record, "payload") else record)
        with self._locked() as (events, append):
            states = self._states(events)
            if record.nonce in states:
                raise CapabilityError("Capability nonce already exists.")
            if any(item["state"] == "armed" for item in states.values()):
                raise CapabilityError("An outstanding capability must be invalidated first.")
            append({"event": "armed", "at": timestamp_text(utc_now()), "record": record.payload()})
        return record

    def consume(self, request, marker):
        request = validate_request(request.payload() if hasattr(request, "payload") else request)
        with self._locked() as (events, append):
            states = self._states(events)
            armed = [item for item in states.values() if item["state"] == "armed"]
            if not armed:
                if any(item["state"] == "consumed" for item in states.values()):
                    raise CapabilityError("Capability nonce was already consumed.")
                raise CapabilityError("No launch capability is armed.")
            if len(armed) != 1:
                raise CapabilityError("Capability journal has multiple outstanding nonces.")
            record = armed[0]["record"]
            try:
                record.assert_matches(request, marker)
            except CapabilityError as exc:
                if timestamp(record.expires_at) <= utc_now():
                    append({
                        "event": "invalidated",
                        "at": timestamp_text(utc_now()),
                        "nonce": record.nonce,
                        "reason": "expired",
                    })
                raise exc
            append({
                "event": "consumed",
                "at": timestamp_text(utc_now()),
                "nonce": record.nonce,
            })
        return record

    def invalidate_all(self, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise CapabilityError("Capability invalidation reason is missing.")
        count = 0
        with self._locked() as (events, append):
            for item in self._states(events).values():
                if item["state"] == "armed":
                    append({
                        "event": "invalidated",
                        "at": timestamp_text(utc_now()),
                        "nonce": item["record"].nonce,
                        "reason": reason,
                    })
                    count += 1
        return count

    def invalidate_expired(self, now=None):
        current = now or utc_now()
        count = 0
        with self._locked() as (events, append):
            for item in self._states(events).values():
                if (
                    item["state"] == "armed"
                    and timestamp(item["record"].expires_at) <= current
                ):
                    append({
                        "event": "invalidated",
                        "at": timestamp_text(current),
                        "nonce": item["record"].nonce,
                        "reason": "expired",
                    })
                    count += 1
        return count

    def rearm(self, previous_nonce, replacement):
        replacement = validate_record(
            replacement.payload() if hasattr(replacement, "payload") else replacement
        )
        with self._locked() as (events, append):
            states = self._states(events)
            previous = states.get(previous_nonce)
            if previous is None or previous["state"] not in {"consumed", "invalidated"}:
                raise CapabilityError("Only an explicitly spent capability may be re-armed.")
            if any(item["state"] == "armed" for item in states.values()):
                raise CapabilityError("An outstanding capability already exists.")
            append({
                "event": "rearmed",
                "at": timestamp_text(utc_now()),
                "previous_nonce": previous_nonce,
                "record": replacement.payload(),
            })
        return replacement

    def latest_spent_nonce(self):
        with self._locked() as (events, _append):
            states = self._states(events)
            spent = [
                nonce for nonce, item in states.items()
                if item["state"] in {"consumed", "invalidated"}
            ]
            return spent[-1] if spent else None

    @staticmethod
    def _states(events):
        result = {}
        for event in events:
            if not isinstance(event, dict):
                raise CapabilityError("Capability journal event is invalid.")
            kind = event.get("event")
            if kind in {"armed", "rearmed"}:
                expected = (
                    {"event", "at", "record"}
                    if kind == "armed"
                    else {"event", "at", "previous_nonce", "record"}
                )
                if set(event) != expected:
                    raise CapabilityError("Capability journal event shape is invalid.")
                timestamp(event["at"])
                record = validate_record(event["record"])
                if record.nonce in result:
                    raise CapabilityError("Capability journal reuses a nonce.")
                if kind == "rearmed" and (
                    event["previous_nonce"] not in result
                    or result[event["previous_nonce"]]["state"]
                    not in {"consumed", "invalidated"}
                ):
                    raise CapabilityError("Capability journal has an invalid re-arm event.")
                result[record.nonce] = {"state": "armed", "record": record}
            elif kind in {"consumed", "invalidated"}:
                expected = (
                    {"event", "at", "nonce"}
                    if kind == "consumed"
                    else {"event", "at", "nonce", "reason"}
                )
                if set(event) != expected:
                    raise CapabilityError("Capability journal event shape is invalid.")
                timestamp(event["at"])
                nonce = event.get("nonce")
                if nonce not in result:
                    raise CapabilityError("Capability journal references an unknown nonce.")
                if result[nonce]["state"] != "armed":
                    raise CapabilityError("Capability journal repeats a terminal event.")
                result[nonce]["state"] = kind
            else:
                raise CapabilityError("Capability journal contains an unknown event.")
        return result

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        existed = self.path.exists()
        fd = os.open(
            self.path,
            os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
            0o600,
        )
        with os.fdopen(fd, "r+b", buffering=0) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            self._assert_trusted(handle)
            if not existed:
                directory_fd = os.open(
                    self.path.parent, os.O_RDONLY | os.O_DIRECTORY
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            handle.seek(0)
            events = []
            for line in handle:
                try:
                    events.append(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise CapabilityError("Capability journal is malformed.") from exc

            def append(event):
                handle.seek(0, os.SEEK_END)
                handle.write(canonical_json(event) + b"\n")
                os.fsync(handle.fileno())

            yield events, append
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _assert_trusted(self, handle):
        if not self.require_root_owned:
            return
        file_stat = os.fstat(handle.fileno())
        directory_stat = self.path.parent.stat()
        if (
            file_stat.st_uid != 0
            or directory_stat.st_uid != 0
            or file_stat.st_mode & 0o077
            or directory_stat.st_mode & 0o022
            or not stat.S_ISREG(file_stat.st_mode)
        ):
            raise CapabilityError("Capability journal or directory is misowned.")
