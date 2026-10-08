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

## Not done (owner decisions / out of time)
- E7 paid-event re-register is free (fix shape needs an owner call), M4 machine_service/maintenance
  without machines, B7 machine-type link UI, M3 certification override API, M11 dashboard print
  tiles, M13 dead `public_print_status_lookup_policy`, R12/R18/R22 and the other OWNER-DECISION rows.
- Unpinned BUILT-UNTESTED rows: R12, E3, E11, E15, I5, M1 (HTTP view), M7 field set.

## Tests actually run (all green unless noted)
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
