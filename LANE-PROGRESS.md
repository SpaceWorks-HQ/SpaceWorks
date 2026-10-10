# Lane 9b — online kiosk routing and operator leases

Branch `lane/9b`, based on `2a7c8227` (lane 9a's finished state). Plan:
`<main>/docs/plans/2026-09-03-forward-plan/phase-9b-online-kiosk.md`. Codex gates waived by the owner;
all work by Claude Opus 5.5. Session 1 ran 2026-10-09 04:13–05:00 IST; resumed 2026-10-10 13:10 IST.

## Stage-1 review (copy of `reviews/stage1-p9b.md`)

The harness refused writes to the main checkout, so the review was written to this worktree's (gitignored)
`docs/plans/2026-09-03-forward-plan/reviews/stage1-p9b.md`; copy it across. Summary:

- Stale facts: makerspaces leaf is `0073_shared_station` (new migration is `0074_station_operator_leases`);
  feature count is 18 -> 19 (not 13); `capabilities.py` is 274 lines; `data_export/classification.py` and
  `references.py` are barrels — rows live in `classification_platform.py` / `references_core.py`;
  `unique_values.py` is split (no row needed).
- Defect 1: `HTTP_ANONYMOUS_PARTICIPANTS` registration is unnecessary — an AllowAny method that calls
  `assert_write_allowed` directly participates automatically (that is how 9a's event session view passes).
  Step 1's split-only `gate_policy_kiosk.py` is therefore dropped; `gate_policy.py` gains three rows (290).
- Defect 2: `StationSessionRevocation` is designed but never registered in the Files/Step 9 lists. Added to
  OMITTED, field snapshot, authority supplement and the D8 literal matrix (all DROP) alongside the lease.
- Defect 3: quarantine (`backup/recovery.enter_quarantine`) must revoke the new authority — it now revokes
  every un-revoked lease. Owner awareness: 9a deliberately keeps StationCredentials live across a deployment
  restore (documented in INVARIANTS), in tension with HANDOVER §7.
- Defect 4: the effective-authority API is `rbac.effective_actions` (local membership ∪ organization grant),
  not `resolve_scope`/`scope_by_action`.
- Defect 5: the `MANAGE_MAKERSPACE  # superadmin only` comment is stale (Space Managers hold it).
- Found in build: extracting the evidence presign into a service makes it an object-mutation site the
  source-gate guard must see; declared in `OBJECT_MUTATION_PARTICIPANTS`.

## Done (all committed)

| Commit | Step |
|---|---|
| `8fe26d89` | 2 — `inventory.kiosk` feature (backend, frontend mirror, workflows, MODULES/README), default off |
| `0fa7ca15` | 3-5, 8 — lease + revocation models/`0074`; admin lifecycle; PIN session + bootstrap; operator lease; settings/throttles/checks/CORS; cleanup beat + beat-less; gate participants; export/tenant/audit registries; quarantine revocation |
| `4478a932` | 6-7 — `evidence/services_upload.py`; kiosk evidence prepare; exact command policy; work package; online dispatcher; INVARIANTS/SOURCE-MAP |
| `313778b3` | 10 (part) + 11 — OpenAPI + generated client; Station routes; `KioskStationPage`; `KioskStationSettings` |
| `d16b2b23` | 9 — catalog digest re-blessed (`7cb4c275…`), D8 matrix, object-mutation participant |
| `e9c391b5` | 10 — scanner/handover shells, `kioskSession.ts` idle/expiry reset + fullscreen/wake lock, PIN reveal UI, `PublicDeskKioskPage`/`ScannerPage` moved out of `PlatformApps.tsx` |
| `5cb96894` | 7 — prospective direct-handout work package; OpenAPI regenerated |

## Deviations from the plan

- Kiosk work/evidence/command URLs live in `makerspaces/station_urls.py`, not `hardware_requests/urls.py`:
  that URLconf is namespaced (`app_name = "hardware_requests"`), which would have changed the planned route
  names. The views themselves are in `hardware_requests/kiosk_views.py`.
- Added `DELETE .../operator-lease/` (operator sign-out).
- The companion audit row is written after the service returns, not in one transaction with it (the direct
  handout service does storage I/O before its own transaction).
- `inventory.kiosk` off refuses the Station session uniformly (403, like the event Station); a sub-capability
  off (e.g. `inventory.self_checkout`) answers 400 on the command.
- `ENUM_NAME_OVERRIDES` pins `EvidenceUrlRequestEvidenceTypeEnum`.
- The frontend handover shell covers reviewed requests (assign box / issue / return-all). Direct handout and
  direct return are server-complete but have no kiosk UI yet; partial-return resolution and asset-QR issue
  are not in the kiosk UI (use the staff console).
- Celery: `tasks_station` is imported from `makerspaces/tasks.py` so autodiscovery registers it.

## Next (for 9c onward)

- Kiosk UI for direct handout/return and per-line return resolutions.
- Offline queue / replay (9c-9e) as planned.

## Tests actually run

See the final section of the lane report; numbers recorded below as they finished.
