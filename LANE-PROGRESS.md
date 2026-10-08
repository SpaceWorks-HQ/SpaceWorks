# Lane `makerspace` — progress

Branch `lane/makerspace`, based on `b7c2ee93`. Temporary file for the owner's checkpoint rule; drop it
when the lane is squashed.

## Done

- (1) Audit and plan: `docs/plans/2026-10-09-makerspace-completeness/00-audit.md` and `01-plan.md` in
  the main checkout (gitignored).
- A `a57fc3ab` module console + superadmin membership revoke honour hard hide / servability (G1, G6).
- B+D `bf37f64b` settings contract: cors read-only, lapsed flag exposed, audit field names,
  api-settings 404-before-403 + servable, return-policy servable, OpenAPI errors (G2, G3, G7, G8, G12).
- split `aa571ab0` `/control/` lifecycle actions moved to `admin_lifecycle_actions.py`.
- C `4decd5d7`+`ba32982b` `/control/` domain edits through `apply_domain_change`; domain-change and
  `/control/` create/edit audits (G4, G5).

## In flight

- F: `recompute_storage` completeness (member-card photos, event-series images, certificates).

## Next

- E: logo/cover OpenAPI 403/404 + envelope OpenAPI pin test.
- F: public directory exclusion tests; INVARIANTS stale MaintenanceLogDocument sentence.

## Tests actually run

- A: new tests 22 passed on the branch; on base `b7c2ee93` the 6 new hidden/unservable tests FAIL
  (regression proof), 16 pass.
- B+D: settings contract + test_notification_secrets, test_audit, test_apiclients, test_admin_api:
  80 passed. On base the 9 new contract tests FAIL, 4 pin-only tests pass.
- C: 12 files (contract, control admin, frontend_domain, domain_verification, saas_hosting,
  makerspace_lifecycle, archive_impact, archive_request_admin, admin_custom_views,
  admin_hidden_scope, capabilities, request_access): 155 passed, 0 failed.
- Frontend: `npx tsc -b` clean after the regenerated client.
