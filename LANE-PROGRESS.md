# LANE combos — progress

Branch `lane/combos` (from `b7c2ee93`). Brief: cross-module combination matrix + fixes.
Matrix + plan: main checkout `docs/plans/2026-10-09-module-combinations/00-matrix.md`, `01-plan.md`
(gitignored; a copy lives in this worktree's ignored `docs/plans/`).

## Done (commits)
- matrix + plan saved
- G2 member-card QRs never reach inventory QR paths (R10, R11, S4)
- G3 lapsed-term rule on every borrow path (R6, R7, R8)
- G4 editions hide every public route of a hidden module (R20, R21, B13, E14, M12, M17)
- G5 event cancel cancels pending charges (E8)

## Next
- G6 notification matrix PATCH + report schedule validation (N4, N11, N12) + pins (N3, N13, N15, N16)
- G7 procurement printer create gates (M15) + pins (M5, N8, B6)
- G1 docs counts (P1-P6, M20, N9) + profile-count pin
- final: module test batch, manage.py check, makemigrations --check, report

## Tests actually run (all green unless noted)
- G2: test_combo_member_card_qr + test_member_cards + test_box_checkout_integrity +
  test_admin_direct_loans + test_stocktake_scan: 53 passed. The new file run against the
  pre-fix code: 3 failed, 1 passed (the bug reproduced).
- G3: test_combo_lapsed_borrowing + makerspaces/test_membership_plans: 21 passed
- G4: test_combo_editions + modules/test_editions + bookings/test_public_api + events calendar x2 +
  machines/test_printer_type_global_identity + modules/test_offstate_machines +
  modules/test_module_contract_matrix + makerspaces/test_module_registry: 112 passed, 18 skipped
- G5: test_combo_event_money + events/test_services + payments/test_domain_charges +
  events/test_event_series: 46 passed
