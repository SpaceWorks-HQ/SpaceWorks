# Space Works — Program Handover (Machine Kernel → Rename → Relocate)

**Date:** 2026-07-20 · **Owner:** Shaan-Shoukath (sole copyright holder) · **Status:** simplified handover.
**Direction change (2026-07-20): monetization/open-core is DROPPED.** There is **no premium tier, no private
`SpaceWorks-Premium` repo, no managed-hosting-only split, no entitlement/billing, no runtime connector, and no
self-host→managed migration tool.** Everything ships in **one public, self-hostable AGPL repo**. The detailed
per-topic specs under `docs/superpowers/specs/` (gitignored) are the authoritative execution detail.

## 0. How to pick this up cold
Read order: **this doc** → machine-kernel spec (`specs/2026-07-19-project-b-machine-kernel-codex-build-spec.md`
+ mapping `specs/2026-07-19-project-b-mapping.md`) → rename plan (`specs/2026-07-20-osmm-to-spaceworks-full-rename-plan.md`).
Design source (external): `C:\Users\SHAANS-PREDATOR\Downloads\SpaceWorks\SpaceWorks-Design`. Build workflow =
Codex-driven, `~/.claude/CLAUDE.md` Stages 1–6. Live build state is in the assistant memory
(`project-b-machine-kernel-build`).

## 0a. Overall order (top-level) — SIMPLIFIED
**PHASE A** finish Project B (machine kernel) → **PHASE B** Space Works full rename + folder relocation. That's it.
(Optional, owner-specified later: a marketing page and open IoT firmware — all self-hostable, no monetization.)

## 0b. Current state (verified 2026-07-20)
- Repo `…\TinkerSpace\Inventory-Manager`, `dev` @ `f77d86e`; many unpushed commits (no upstream set).
- **Project B: B4/B5/B6 + B7a/B7b/B7c DONE + committed + green.** B7d (irreversible `DeleteModel` table drop)
  is **AUTHORIZED by owner (2026-07-21)** and being executed — the earlier "stop before B7d" hold is LIFTED.
  Sequence: **finish B7 (incl. B7d) → then rename/relocate.**
- **Worktrees: all removed** (only `dev` remains).
- Remote reachable as `SpaceWorks-HQ/SpaceWorks` (old URL redirects). **Only one repo is needed: `SpaceWorks`
  (public AGPL).** Any `SpaceWorks-Premium` repo is now irrelevant and can be ignored/deleted.

## 0c. Locked decisions (do not re-litigate)
- **Everything is free + self-hostable in ONE AGPL repo.** No premium, no private repo, no managed-only features.
  The prior "open-core Model B" is CANCELLED. All modules (membership, events, bookings, analytics, maintenance,
  presence, self-checkout, machines, printing-as-machine-type, etc.) ship in the single self-hostable repo.
- **AGPL stays** on the whole repo (sole owner; no forced-open concern since nothing is withheld).
- **Full rebrand OSMM → Space Works** (org `SpaceWorks-HQ`; repo `SpaceWorks`; domain `space-works.tech`;
  id `spaceworks`; display "Space Works").
- **Sequence: finish machine kernel (Project B) → rename → relocate.** Brand = one mark from the design kit.

## 0d. Open decisions still needed from owner
- Docker volumes preserve vs disposable (default: disposable dev seed).
- Which mark from `Selected Marks - Full Kits.html`; keep/drop the "Open Source Makerspace Manager" tagline.
- (No IP-counsel / premium / private-repo decisions remain — those plans are deleted.)

---

# PHASE A — Finish Project B (machine kernel) FIRST
Generalize `apps/printing` into the `apps/machines` kernel (3D printing = a MachineType). B4 (data+logic cutover),
B5 (retire print_manager), B6 (generic API + frontend fold-in) are DONE. **B7 remaining:** B7a (port the last
printing-only features to the kernel) → B7b (procurement/warranty FK migrations + remove the `linked_print_printer`
bridge) → B7c (delete printing runtime code + config/PII cleanup + kernel-only cutover) → B7d **AUTHORIZED
2026-07-21** (the irreversible `DeleteModel` table-drop; migration carries a fail-closed guard = flip+reconcile
ALL tenants first, so real deployments can't drop with unreconciled data). Detail: `specs/2026-07-2*-project-b-B7*`
+ the assistant memory resume block. Commit each; suite green.

# PHASE B — Full rename + folder relocation (only after PHASE A) — Codex-hardened
**B.1 — Safeguard (no data loss before any move).** Put remaining WIP on a dated recovery branch, push it. `git fetch`
+ verify `origin/dev` is a fast-forward target (no upstream set), set upstream, push `dev`. Update remote URL →
`https://github.com/SpaceWorks-HQ/SpaceWorks.git`. External `git bundle --all` stored OUTSIDE the moved folder
(verify it); `git tag pre-relocation`. (Bundle excludes gitignored files — see B.3.)

**B.2 — Worktrees.** Already removed; assert `git worktree list` = exactly one entry and no `Inventory-Manager-*`
siblings before proceeding.

**B.3 — Relocate (same-volume move; Windows pre-move gate).** Close editors/dev servers/Compose; confirm same volume
`C:` and target `…\SpaceWorks\SpaceWorks` doesn't exist. Move `…\TinkerSpace\Inventory-Manager` →
`…\Downloads\SpaceWorks\SpaceWorks`. Reopen shell at new path; `git status`/`git fsck`. **Ignored artifacts ride with
the folder** — verify present: `backend/.env`, root `.env`, `docker-compose.override.yml`, gitignored `specs/`,
local tooling. (Fresh clone is FALLBACK-ONLY; it omits these.)

**B.3a — Local Docker data decision (before B.6 rename).** Renaming `COMPOSE_PROJECT_NAME`/containers orphans named
volumes `makerspace_manager_pgdata`+`minio_data`. Decide preserve (`pg_dump` + MinIO snapshot) vs disposable
(re-seed via `seed_demo`/`setup_instance`). Default: disposable dev seed.

**B.5 — Import the ONE selected design.** Owner picks one mark from `SpaceWorks-Design/Selected Marks - Full Kits.html`
→ export SVG/PNG → place as the rename's brand assets (`frontend/public/spaceworks-logo.svg`, icon, `docs/brand/*`,
banner, favicon).

**B.6 — Full rename OSMM → Space Works.** Execute `specs/2026-07-20-osmm-to-spaceworks-full-rename-plan.md`
(Codex-reviewed; 8 coverage findings folded: `_osmm-verify` dual-accept, ALL container literals, persisted-key reset,
expanded file/test lists, tightened exclusions, regenerate-don't-edit generated files). One isolated commit using the
B.5 asset. Regenerate OpenAPI + `api.ts`; grep-verify **tracked** files to zero; tests green. Update `CLAUDE.md` +
memory (paths, brand, containers, remote).

**PHASE B done when:** everything pushed to `SpaceWorks-HQ/SpaceWorks`; working copy at `…\SpaceWorks\SpaceWorks`;
no stale worktrees; rename verified (grep zero, tests green, API regenerated); CLAUDE.md/memory updated.

---

# (Optional, later) Self-hostable extras — owner to spec
Marketing page and open IoT firmware (Apache-2.0 firmware + CERN-OHL-P hardware) built on the kernel — all
self-hostable, no monetization. Not scheduled; specify if/when wanted.
