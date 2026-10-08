# Lane `makerspace` — progress

Branch `lane/makerspace`, based on `b7c2ee93`. Temporary file for the owner's checkpoint rule; it is
meant to be dropped when the lane is squashed.

## Done

- (1) Audit and plan written: `docs/plans/2026-10-09-makerspace-completeness/00-audit.md` and
  `01-plan.md` in the main checkout (gitignored; a copy sits in this worktree's gitignored
  `docs/plans/`).

## In flight

- (2) Gap groups A–F from `01-plan.md`.

## Next

- A: module console + membership revoke honour hard-hide / servability.
- B: settings serializer integrity (cors read-only, lapsed flag, audit field names).
- C: `/control/` makerspace edits through the domain transition + audits.
- D: api-settings / return-policy 404-before-403 + servable.
- E: OpenAPI error responses + pin test.
- F: directory / quota tests, `recompute_storage` completeness.

## Tests actually run

None yet.
