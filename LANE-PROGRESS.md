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
- F `b59e6d46` `recompute_storage` counts member-card photos, event-series images, certificates;
  public directory exclusion tests; stale INVARIANTS paragraph fixed (G10, G13).
- E `eb769267` image routes document 403/404; envelope OpenAPI pin test (G9).
- G11 `4c87125a` managed `assets` quota test.

## In flight

- Final broad verification run (see below).

## Not built (owner decisions, `00-audit.md` §11)

Key rotation; ORG-only hide self-lockout; last-Space-Manager guard; tenant usage page; console
surface for account-less requests; limit-key vocabulary.

## Tests actually run

- A: new tests 22 passed; on base `b7c2ee93` the 6 new tests FAIL (regression proof).
- B+D: contract + notification_secrets, audit, apiclients, admin_api: 80 passed. On base the 9 new
  contract tests FAIL.
- C: 12 files, 155 passed, 0 failed.
- F: reconciler gaps 4 passed; directory + limits enforcement + events image + public inventory:
  63 passed before the fixture fix, reconciler file re-run 4 passed.
- E: OpenAPI pin + public images: 22 passed.
- G11: 2 passed.
- Frontend: `tsc -b` clean, `npm test` 64 files / 277 tests passed, `npm run build` ok.
- `manage.py check` (1 environmental AUDIT_MAC warning), `makemigrations --check` no changes,
  `diff CLAUDE.md AGENTS.md` empty, `git diff --check` clean.
