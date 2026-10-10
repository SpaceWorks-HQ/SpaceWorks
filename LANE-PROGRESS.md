# Lane w2-notify - implementation and review ready for coordinator validation

All changes are inside this worktree, unstaged. No git state-changing command was run.

## Completed

- Separate encrypted per-User inbox/read state, matrix fan-out and private SSE hints.
- Member/staff inbox and preference centre, with recipient-separated query keys.
- Scoped unified delivery screen, filters, generation retry and self/destination tests.
- RFC 8058 signed unsubscribe; mandatory mail protection; tenant/platform manual
  suppression; queued delivery rechecks and minimized platform recovery logs.
- Opt-in structured webhook v2 and schema catalogue; default v1 compatibility.
- F1 retention: 90 days read/sent/skipped, 365 days failed; unread/in-flight retained.
- Data hygiene, User-FK, encryption, tenant projection/authority and source-gate entries.

## Review pass

The strict review found and fixed recipient-selection/blanket opt-out bypasses,
no-email requester omissions, unsafe link normalization, default/legacy alert drift,
stale callback gates, cross-tenant service retry trust, delegated revoked-member
access, tombstone opt-out bypass, missing backup object exemption, platform retention
and suppression gaps, platform skipped-log PII leakage, and incomplete schema/env docs.
All changed text uses LF. AGENTS.md and CLAUDE.md stay byte-identical and unmodified.
See [w2-notify-PROGRESS.md](w2-notify-PROGRESS.md) for each defect, every file/test,
migration dependencies, skipped items and the outside-lane payments-family defect.

## Local checks

- npx.cmd tsc -b: passed, exit 0.
- Relevant Vitest: 68 tests passed across eight files.
- python -m py_compile on every changed backend Python file: 81 files, passed.
- Source-gate AST check passed (38 tasks, 4 webhooks, 34 HTTP participants,
  6 lifecycle, 114 objects, 12 fan-outs).
- git diff --check clean; index empty; every touched file <=300 lines.

## Remaining / coordinator validation

No backend database tests were run or claimed passed. The sandbox has no reachable
Docker/Postgres and no Django installed. Run ./scripts/dev.sh test with the eight new
backend test files in the full handoff, especially test_notification_review_f2.py and
 test_platform_email_suppression_f2.py. Run existing notification/email/F3, encryption,
F1, module purge, separability, backup and tenant-migration guards; migration drift,
system/schema checks; regenerate the two frontend OpenAPI artifacts in integration.
Codex doctor could not resolve managed configuration/connectivity here; external CLI
review was unavailable. No owner decision blocks the implemented scope.

## Migrations / skips

- notifications/0002_personal_inbox.py depends on notifications.0001_initial and
  swappable AUTH_USER_MODEL.
- integrations/0029_personal_delivery_controls.py depends on
  integrations.0028_research_notification_families and swappable AUTH_USER_MODEL.
  The review updated this unshipped migration for platform suppression uniqueness.
No extra migration, module key or environment variable. SMTP has no provider webhook;
manual suppression implements the proposed fallback. Retention overrides and other
provider transports/digests/quiet hours/member push delivery remain outside scope.
