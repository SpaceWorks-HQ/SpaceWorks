# Lane suite-fixes progress

Branch `lane/suite-fixes`, based on `dev` at `b7c2ee93`. Goal: find the real zero-red baseline of that
commit and fix any real failures.

## Plan

1. Run the full backend suite once:
   `./scripts/dev.sh test -q -rfE --tb=short -p no:randomly` (log to an untracked file).
2. Triage each failure as a code regression, a wrong test assumption, or environmental. Fix the real
   ones (one commit each), then re-run only the affected files.
3. Run the frontend suite once: `npm ci && npx tsc -b && npm test && npm run build`.

## Status (updated 2026-10-09 01:05 IST)

- **Frontend: green.** `npm ci` ok, `npx tsc -b` exit 0, `npm test` (vitest 4.1.10) 64 files /
  277 tests passed, `npm run build` exit 0.
- **Backend run 1** started 00:16 IST and was killed at **67%** when the Claude session and Docker
  Desktop restarted (~01:00 IST). It had **0 failures and 0 errors** up to that point, including the
  39%, 50% and 57% marks where the unidentified 2026-10-08 failures were reported. The only non-pass
  marks were xfails (`x`) between 66% and 67%.
- **Backend run 2** started 01:05 IST from scratch with the same command. In progress.

## Remaining

- Finish run 2 and triage anything red.
- Final counts and the report.
