# LANE combos — progress

Branch `lane/combos` (from `b7c2ee93`). Brief: cross-module combination matrix + fixes.
Matrix + plan: main checkout `docs/plans/2026-10-09-module-combinations/00-matrix.md`, `01-plan.md`
(gitignored; a copy lives in this worktree's ignored `docs/plans/`).

## Done (commits)
- b7c55eb9 G2 member-card QRs never reach inventory QR paths (R10, R11, S4)
- ec4a25ad G3 lapsed-term rule on every borrow path (R6, R7, R8)
- 3df728ab G4 editions hide every public route of a hidden module (R20, R21, B13, E14, M12, M17)
- 84ca5fc6 G5 event cancel cancels pending charges (E8)
- 803eabe0 G6 notification matrix PATCH + report schedule validation (N4, N11, N12) + pins N13, N15
- 2bfd0589 G7 procurement printer create takes the machine gates (M15) + pins M5, N8, B6
- e1622d78 G1 docs counts (P1-P6, M20) + profile-count pin
- e285212a pins N3, N16

## Current handoff (2026-10-10, unstaged)

Added the remaining requested regression pins; database execution is pending with the coordinator.
No production code, routes, schema snapshots, models or migrations changed in this follow-up.

- R12: explicit `container_id` is retained with `containers` on and silently dropped with it off;
  a core box QR scan still assigns the scanned container with the module off, even when an
  unrelated `container_id` was sent. Issue evidence, issued stock and actor attribution are checked.
- E3: strengthened the existing free-event test by explicitly enabling charge tracking and
  registering for a paid control event through HTTP, proving the real payment seam works.
- E11: materialize and publish a two-occurrence paid series, register the same member in both,
  waitlist another member in each, and assert independent capacity and two distinct charges.
- E15: create real walk-in members with no contacts or existing contacts; staff registration
  requires missing contacts, accepts fallbacks, preserves account-first email/phone, and does
  not overwrite the person's stored contact data.
- I5: inventory detail and stats answer 200 in the makerspace edition, 404 in events/bookings,
  and 200 again when the edition is restored without changing the records or modules.
- M1 HTTP: missing, expired and revoked grants refuse with typed certification details and
  create no service job/audit; live grants and feature-off allow a member-attributed audited job.
- M7: anonymous consumable responses have exactly `id`, `material`, `color`, with real values.

Files changed in this follow-up:
- `LANE-PROGRESS.md`
- `backend/tests/modules/test_combo_event_pins.py` (modified)
- `backend/tests/modules/test_combo_editions.py` (modified)
- `backend/tests/modules/test_combo_handover_pins.py` (new)
- `backend/tests/modules/test_combo_public_machine_pins.py` (new)

Tests added/strengthened (coordinator must run):
- `test_combo_handover_pins.py::test_direct_handout_only_keeps_explicit_container_selection_when_module_on`
  (on/off, 2 cases)
- `test_combo_handover_pins.py::test_direct_handout_box_scan_still_sets_container_with_containers_off`
- `test_combo_event_pins.py::test_a_free_event_registers_without_recording_a_charge` (strengthened)
- `test_combo_event_pins.py::test_series_occurrences_have_independent_capacity_and_registration_charges`
- `test_combo_event_pins.py::test_staff_registration_email_is_a_fallback_and_account_email_wins`
  (blank/existing contacts, 2 cases)
- `test_combo_editions.py::test_editions_hide_public_inventory_detail_and_stats`
  (2 routes x 2 hidden editions, 4 cases)
- `test_combo_public_machine_pins.py::test_public_machine_submit_enforces_certification_at_http_boundary`
  (5 grant/feature states)
- `test_combo_public_machine_pins.py::test_public_printer_pools_expose_only_id_material_and_color`

Coordinator command:
```bash
./scripts/dev.sh test tests/modules/test_combo_handover_pins.py tests/modules/test_combo_event_pins.py tests/modules/test_combo_editions.py tests/modules/test_combo_public_machine_pins.py
```

Validation performed here: Python AST syntax checks and `git diff --check`; all four test
files remain below 300 lines. No database test was run, and no runtime pass is claimed.
`codex doctor` could not load configuration/resolve CODEX_HOME and could not reach the
provider endpoint in this sandbox; external CLI review remains for the coordinator.
No staging or other state-changing git command was used.

## Remaining owner decisions (unchanged)

The main-checkout matrix and plan provide no defaults for B7, M3, M4, M11 or M13, and
the plan explicitly lists all five under owner decisions. They were therefore left
unchanged, as instructed; E7 was also left unchanged explicitly.

- B7: expose the machine-type link in the bookable-space editor.
- M3: expose a certification override reason through the staff service API.
- M4/N17: choose module dependencies plus data migration versus surface gating when machines is off.
- M11: choose dashboard print-counter behavior across printing/machine_service off-states.
- M13: enforce or remove `public_print_status_lookup_policy` (no decision supplied).
- E7: paid-event re-registration needs a fresh-charge/registration or refusal policy.
- R12: silent field drop versus 400 (only current behavior was pinned).
- R18: account-less deposits/late fees; R22: previously shared request-status links across editions.
- E4: charge tracking off with rail on; E16/B14/M19: lapsed-term eligibility outside borrowing.
- E17: staff-registration waiver policy; E18: settled registration refund policy.
- B8: booking certification override API; B9: eligibility drift at approval.
- M2: certification requirements without membership; M9: consumable pool module ownership;
  M16: procurement machine-type narrowing with machines off.
- N6: recipient roles without feature authority; N10: building undeliverable scheduled reports.

Out-of-task finding: the planning matrix is stale relative to this worktree in places.
B7 already has backend machine-type serializer/service plumbing and a regression test;
M11 already has a printing-module dashboard guard and a regression test in
`test_combo_machines.py`. Those existing changes were not altered. No additional
out-of-task application defect was confirmed during this follow-up.

## Historical tests actually run (previous lane work, not this follow-up)
- G2: test_combo_member_card_qr + test_member_cards + test_box_checkout_integrity +
  test_admin_direct_loans + test_stocktake_scan: 53 passed. New file against pre-fix code: 3 failed, 1 passed.
- G3: test_combo_lapsed_borrowing + makerspaces/test_membership_plans: 21 passed
- G4: test_combo_editions + modules/test_editions + bookings/test_public_api + events calendar x2 +
  machines/test_printer_type_global_identity + modules/test_offstate_machines +
  modules/test_module_contract_matrix + makerspaces/test_module_registry: 112 passed, 18 skipped
- G5: test_combo_event_money + events/test_services + payments/test_domain_charges + events/test_event_series: 46 passed
- G6: test_combo_notifications_reports + operations/test_report_schedules + test_notification_rules_api +
  test_notification_channel_modules_p10: 55 passed
- G7: test_combo_machines + test_procurement_move_to_inventory + test_b7a_kernel_procurement_move +
  machines/test_certifications: 29 passed + 1 failed (my own test's setup), fixed, re-run: 5 passed
- G1: test_combo_profiles: 11 passed
- N3/N16 pins: 2 passed
- Final batch: see below
- manage.py check: 1 warning (AUDIT_MAC_MASTER_KEY unset in the one-off env), 0 errors;
  makemigrations --check --dry-run: No changes detected; spectacular vs committed snapshot: only the
  pre-existing `MakerspaceArchiveRequest.status default: pending` drift (present at b7c2ee93, not this lane)
