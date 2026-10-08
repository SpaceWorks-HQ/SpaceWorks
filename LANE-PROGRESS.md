# Lane `cloud` — progress

Branch `lane/cloud`, forked from `dev` at `b7c2ee93`.

The brief was "online cloud services — all conditions", in two steps:

1. An audit matrix.
2. Closing every MISSING / BUILT-UNTESTED cell.

## Where the audit lives

- **Committed copy:** `LANE-CLOUD-AUDIT/00-audit.md` and `01-plan.md`.
- **Gitignored worktree copy:** `docs/plans/2026-10-09-cloud-completeness/`, which the
  coordinator copies into the main checkout. The harness refuses writes outside the worktree.

## Done (one commit each, oldest first)

1. **Audit + plan.**
2. **G1 — outbound fail-safe.**
   - `dispatch_email` no longer hits `UnboundLocalError`.
   - The chat quota now fails open.
   - Cron, Telegram-webhook and Razorpay header-secret checks no longer 500 on non-ASCII
     input.
   - `api-key-requests?makerspace=abc` returns 400.
   - Tests: the channel provider-failure matrix, the re-queue action, and HMAC skew /
     undecryptable secret / cache outage.
3. **G2 — HTTPS redirect exemption for the internal probes.**
4. **G3 — live SSE resilience.** A bad URL gives 503, a lost Redis ends the stream cleanly,
   and pubsub is always closed.
5. **G4 — updates.**
   - Stale `RUNNING` is recovered.
   - The no-op audit meta is honest.
   - `update.sh` resets the version marker on rollback and bounds `curl`.
   - Docs now say `PlatformUpdateSettings`.
6. **G5 — health parity.** Adds `legacy_deliveries` and a console rooms block (vitest + axe).
7. **G6 + G7.**
   - `/control/` platform-integration edits are audited (`config/admin_audit.py`).
   - The social-settings API applies the lockout guard.
8. **G8 — OpenAPI.**
   - Error responses documented on every in-scope route (`apps/openapi_errors.py`), pinned by
     `tests/test_cloud_openapi_errors.py`.
   - Schema snapshot regenerated; `api.ts` unchanged.
9. **G9 — environment.**
   - New `docs/environment-reference.md` (all 247 names) plus a drift test.
   - `METRICS_TOKEN` / `SENTRY_*` now passed through the prod and cloud compose files.
   - Env examples updated.
10. **G10 — scheduler.** An unknown `--task` is now a `CommandError`; the misleading test was
    renamed.
11. **Identity providers.**
    - JWKS returns 503 (not 500) on an array body or a mid-body read failure.
    - Platform email with an undecryptable password counts as not configured.
    - Tests: Twilio, FCM and JWKS failure matrices.
12. **OIDC unlink.** An `oidc:<slug>` identity can now be unlinked.
13. **Hosting tests.** DNS failure shapes and probe 503s.

## Mid-flight (uncommitted, tests running)

- `PeriodicTaskRun` read-only `/control/` page (`apps/operations/admin_scheduling.py`), its
  `GLOBAL_ADMIN_MODELS` entry, and `tests/test_scheduler_control_visibility.py`.
- `tests/test_hosting_conditions.py`: archived domain loses TLS and host admission; subdomain
  request audited; self-host provisioning refused.
- `tests/payments/test_connect_webhook_signatures.py`.
- Docs: a `PROJECT-HISTORY.md` entry and an `INVARIANTS.md` "Cloud-completeness rules" block.

## Tests actually run (`./scripts/dev.sh test ... -p no:randomly`)

| Run | Scope | Result |
|---|---|---|
| run1 | Pre-fix reproduction | 90 passed, 3 failed (2 expected bug reproductions + 1 test bug, since fixed) |
| run2 | G1 + related suites | 269 passed |
| run3 | G2–G5 + related suites | 133 passed |
| run4 | G6/G7 + related suites | 167 passed |
| run5 | G8 schema + notification/email-template/modules/telegram/admin_api/saas/recovery-gate suites | 333 passed, 18 skipped |
| run6 | env drift, env surface, `host_orchestration_surface_h1a`, platform updates, scheduled tasks, `host_pointer_identity_h1b` | 72 passed, 3 skipped, 1 failed |
| run7 | Provider failure files + social/oidc/email/push/phone suites | 169 passed |
| run8 | DNS, hosting, probes, `domain_verification`, `saas_hosting`, `frontend_domain`, metrics, `host_readiness` | 101 passed |
| frontend | `npm test` | 279 passed |
| frontend | `npx tsc -b` | clean |
| frontend | `npm run build` | ok |

The run6 failure is `test_host_orchestration_surface_h1a.py::test_compose_wrapper_unsets_ambient_pointer_and_layers_pointer_last`.
Its stub uses a `#!/usr/bin/python3` shebang, but the backend image has no `/usr/bin/python3`.
This is environmental and unrelated to this lane: it touches a test-owned stub and
`scripts/spaceworks-compose.sh`, which this lane did not change.

Checks: `manage.py check` reports only the env-dependent `AUDIT_MAC_MASTER_KEY` warning, and
`makemigrations --check --dry-run` reports "No changes detected".
