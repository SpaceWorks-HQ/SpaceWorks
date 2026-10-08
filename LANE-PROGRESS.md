# Lane suite-fixes progress

Branch `lane/suite-fixes`, based on `dev` at `b7c2ee93`. Goal: find the real zero-red baseline of that
commit and fix any real failures.

## Plan

1. Run the full backend suite once:
   `./scripts/dev.sh test -q -rfE --tb=short -p no:randomly` (log to an untracked file).
2. Triage each failure as a code regression, a wrong test assumption, or environmental. Fix the real
   ones (one commit each), then re-run only the affected files.
3. Run the frontend suite once: `npm ci && npx tsc -b && npm test && npm run build`.

## Status (updated 2026-10-09 04:25 IST)

- **Frontend: green.** `npm ci` ok, `npx tsc -b` exit 0, `npm test` (vitest 4.1.10) 64 files /
  277 tests passed, `npm run build` exit 0.
- **Backend run 1** (00:16 IST) was killed at 67% by a Docker Desktop restart. It had no failures up to
  that point.
- **Backend run 2** (01:05 IST, full suite, same command) completed at b7c2ee93:
  **6 failed, 6213 passed, 21 skipped, 29 xfailed** in 66 min. No failure before the 98% mark, so the
  four failures reported around 39%, 50% and 57% on 2026-10-08 did not reproduce. All six were caused
  by `dev.sh test` (4e378680) mounting the repository root at `/workspace`, which makes the "host-only"
  tests think they are on the host:
  - `tests/test_host_orchestration_surface_h1a.py::test_compose_wrapper_unsets_ambient_pointer_and_layers_pointer_last`:
    the fake `docker` stub had `#!/usr/bin/python3`, which is not in the python:3.12 image (exit 127).
    Fixed in `3bfc38a1` (the stub now uses `sys.executable`). The test now runs and passes in the image.
  - `tests/test_privileged_script_modes.py` (4 parametrised `test_operator_entry_point_is_executable`
    cases and `test_no_shipped_script_directly_executes_a_non_executable_sibling`): the image has no
    `git`, so `FileNotFoundError: 'git'`. Fixed in `7a6a8de5` (also skips when git cannot read the
    checkout; CI's host job still enforces it). The modes they check are 100755 at b7c2ee93.
  - Re-run of both files: 23 passed, 8 skipped.
- **Backend run 3** (04:22 IST, full suite with `-rfEs`) is confirming the branch head. In progress.

## Remaining

- Finish run 3 and record its counts.
