"""Explicit, side-effect-free checks over existing operational signals."""

from dataclasses import dataclass
from datetime import timedelta


def result(key, status, message, link, makerspace_id=None):
    return {"key": key, "status": status, "message": message,
            "fix_url": link, "makerspace_id": makerspace_id}


def backup_check(data, now):
    if data["has_error"] or data["status"] == "failed":
        status, message = "error", "The latest deployment backup failed."
    elif not data["automatic_enabled"]:
        status, message = "ok", "Automatic backups are disabled."
    elif not data["last_success_at"]:
        status, message = "warn", "No successful scheduled backup has been recorded."
    else:
        age = now - data["last_success_at"]
        cadence = timedelta(minutes=data["cadence_minutes"])
        status = "error" if age > cadence * 3 else "warn" if age > cadence * 1.5 else "ok"
        message = "Deployment backup is overdue." if status != "ok" else "Deployment backup is current."
    return [result("backup", status, message, "/admin/backup-restore")]


def offsite_check(data, now):
    if not data:
        return [result("offsite", "warn", "No active offsite destination is configured.",
                       "/admin/backup-restore")]
    return [result(
        "offsite", "error" if row["has_error"] or row["state"] == "abandoned"
        else "ok" if row["state"] == "bytes_verified" else "warn",
        f"Offsite destination {row['name']}: "
        + ("needs attention; " if row["has_error"] else "")
        + f"latest copy {row['state'].replace('_', ' ')}.",
        "/admin/backup-restore",
    ) for row in data]


def scheduler_check(data, now):
    return [result("scheduler", row["status"],
                   f"{row['name']}: " + {
                       "ok": "recent execution recorded.",
                       "warn": "no execution within three times its cadence.",
                       "error": "latest execution failed.",
                   }[row["status"]], "/admin/platform-dashboard#scheduler")
            for row in data]


def updates_check(data, now):
    if data is None:
        return [result("updates", "ok", "The in-app updater is disabled.", "/admin/platform")]
    status = "error" if data["status"] == "failed" else "warn" if data["pending"] else "ok"
    return [result("updates", status, {
        "ok": "No platform update is pending.",
        "warn": "A platform update is available or in progress.",
        "error": "The latest platform update failed.",
    }[status], "/admin/platform")]


def _tenant_result(data, key, status, message, tab="settings"):
    space = data["space"]
    return [result(key, status, f"{space.name}: {message}",
                   f"/m/{space.slug}/admin/{tab}", space.pk)]


def email_check(data, now):
    if "email" not in data["space"].enabled_modules:
        return _tenant_result(data, "email", "ok", "email module is disabled.")
    health = data["health"]
    email, smtp = health["email"], health["smtp"]
    if email.get("status") == "error" or smtp.get("status") == "error":
        status, message = "error", "email health reports an error."
    elif email.get("failed"):
        status, message = "error", "failed email deliveries need attention."
    elif (email.get("status") != "ok" or smtp.get("status") != "ok"
          or not smtp.get("configured")):
        status, message = "warn", "email is unconfigured, stalled or could not be checked."
    else:
        status, message = "ok", "email delivery is healthy."
    return _tenant_result(data, "email", status, message,
                          "email-log" if email.get("failed") else "settings")


def telegram_check(data, now):
    if "telegram" not in data["space"].enabled_modules:
        return _tenant_result(data, "telegram", "ok", "Telegram module is disabled.", "api-access")
    health = data["health"]
    chat = health["chat_destinations"]
    destinations = [r for r in chat.get("destinations", []) if r["channel"] == "telegram"]
    rooms = [r for r in destinations if r["is_active"]]
    legacy = chat.get("legacy_deliveries", {}).get("telegram", {})
    failed = legacy.get("failed", 0) + sum(r.get("failed", 0) for r in rooms)
    # Existing destinations suppress legacy delivery, including inactive ones.
    configured = all(r.get("configured") for r in rooms) if rooms else (
        not destinations and health["telegram"].get("configured")
    )
    status = "error" if failed or health["telegram"].get("status") == "error" else (
        "warn" if not configured or chat.get("status") == "unknown"
        or health["telegram"].get("status") != "ok" else "ok"
    )
    return _tenant_result(data, "telegram", status, {
        "ok": "Telegram delivery is healthy.",
        "warn": "Telegram is unconfigured or could not be checked.",
        "error": "Telegram delivery needs attention.",
    }[status], "api-access")


def storage_check(data, now):
    row = next(r for r in data["usage"]["resources"] if r["key"] == "storage")
    used, limit = row["used"], row["limit"]
    status = "ok"
    if limit is not None:
        if used > limit:
            status = "error"
        elif limit > 0 and used >= limit * 0.9:
            status = "warn"
    return _tenant_result(data, "storage", status, {
        "ok": "storage is within its allowance.",
        "warn": "storage is at least 90% of its allowance.",
        "error": "storage is over its allowance.",
    }[status], "usage")


def domain_check(data, now):
    space = data["space"]
    status = "ok"
    if space.frontend_domain:
        status = {"verified": "ok", "pending": "warn", "failed": "error"}.get(
            space.frontend_domain_status, "warn",
        )
    return _tenant_result(data, "domain", status, {
        "ok": "custom domain is verified or not configured.",
        "warn": "custom domain verification is pending.",
        "error": "custom domain verification failed.",
    }[status])


@dataclass(frozen=True)
class PlatformProblemCheck:
    key: str
    scope: str
    evaluate: object


PROBLEM_CHECKS = (
    PlatformProblemCheck("backup", "platform", backup_check),
    PlatformProblemCheck("offsite", "platform", offsite_check),
    PlatformProblemCheck("scheduler", "platform", scheduler_check),
    PlatformProblemCheck("updates", "platform", updates_check),
    PlatformProblemCheck("email", "tenant", email_check),
    PlatformProblemCheck("telegram", "tenant", telegram_check),
    PlatformProblemCheck("storage", "tenant", storage_check),
    PlatformProblemCheck("domain", "tenant", domain_check),
)
