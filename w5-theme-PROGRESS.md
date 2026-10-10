# w5-theme progress

Implemented: shared backend/frontend WCAG sRGB contrast contract, automatic fill
foreground, hover/pressed variants, light/dark link-ink derivation, all-or-nothing
legacy palette fallback scoped to public/member pages, typed settings validation,
and a staff colour editor with both-mode live preview and named failing pairs.
Split the existing 351-line index.css component layer into styles/components.css.
Blank default colours now mean the product palette; no model/schema migration.

Implementation complete. Tint strengths are derived to protect ordinary/muted
body text as well as secondary ink, and bootstrap sanitizes malformed/unsafe
restored themes before publishing them. Primary actions on the public catalogue,
events, loans/self-checkout and printing now use the secondary button family.

Verification: focused vitest run: 7 files / 40 tests passed; production TypeScript,
Vite and PWA build passed. Python syntax checked; no pytest/database tests run.
All changed files remain below 300 lines; git diff --check is clean.

Remaining for coordinator: run backend/tests/makerspaces/test_theme_contrast.py,
backend/tests/makerspaces/test_theme_config.py,
backend/tests/makerspaces/test_makerspace_settings_contract.py,
backend/tests/test_frontend_theme_contrast.py and
backend/tests/test_platform_bootstrap.py. Regenerate the OpenAPI snapshot/client,
run the independent review gate and owner visual QA. No git mutations, staging,
commits, merges or pushes performed.

Added backend tests (test_theme_contrast.py):
- test_wcag_srgb_contrast_math
- test_custom_palette_passes_every_text_and_ui_pair_in_both_modes (5 colours)
- test_dark_derivation_matches_frontend_golden_values
- test_opaque_aa_is_not_enough_for_existing_translucent_counters
- test_serializer_and_control_model_refuse_unsafe_palette
- test_blank_defaults_use_product_palette_and_meet_aa
- test_validation_surfaces_match_rendered_css_and_frontend_contract
- test_tint_strength_protects_normal_and_muted_text
- test_theme_patch_contrast_400_does_not_write_or_audit
- test_dark_brand_fill_is_accepted_and_audited
- test_bootstrap_falls_back_for_invalid_restored_theme (4 stored values)

Frontend tests added/updated:
- lib/brandColours.test.ts: WCAG maths/shorthand parsing, both-mode palettes
  (5 colours), automatic foreground, hover/active derivation, dark/tint link ink,
  counter opacity failures, legacy/empty fallback, scoped tokens, safe body tints.
- features/inventory/PublicInventoryBranding.test.tsx: central/single page tokens,
  theme-change derivation without root overrides, tenant-navigation fallback.
- features/members/MemberAreaBranding.test.tsx: light/dark/invalid palette tokens
  and retained support contacts (expanded existing test).
- features/staff/MakerspaceThemeSettings.test.tsx: live failing pair readout,
  successful PATCH preserving keys/cache invalidation, failed write/input retention.

Environment: codex doctor cannot resolve configuration/home and cannot reach the
inference endpoint, so nested CLI plan/review gates are unavailable. Coordinator
must run its review gate. Footer hiding is explicitly skipped (managed-tier owner
decision); this lane adds no feature/module key, model or migration. No new owner
decision blocks the requested colours. Schema/client generation is intentionally
left to the coordinator as instructed.

Outside-scope defect noticed: bootstrap still merges branding_config without a
shape check, so a malformed restored branding_config can raise during bootstrap;
theme_config now has the safe fallback. Not changed in this colour lane.

## Review pass (2026-10-11)

Completed the strict review of the complete unstaged lane diff, binding repository
rules, both research briefs, and the prior LANE-PROGRESS.md handoff. The requested
w5-theme-PROGRESS.md was absent; it now contains the same implementation history
and this review handoff. All changes remain unstaged. No state-changing git command
was used.

Defects found and fixed:
- Stored falsy non-string colours (0, false, null) could bypass the frontend check.
  The runtime report now validates object shape and explicit string colour values;
  unsafe palettes use the whole product palette in both modes. The editor safely
  initializes malformed colour fields so managers can repair restored values.
- The backend fallback discarded valid mode and legacy logo_url when colours were
  unsafe. public_theme_config now preserves independently valid presentation keys,
  resets unsafe colours, and never rewrites the makerspace or emits a spurious audit.
- Nested member-directory tint blocks compounded translucent backgrounds beyond the
  checked alpha. Brand tint utilities now mix onto an opaque neutral panel base;
  directory profiles keep a neutral base for nested identity cards and hover states.
- Contrast omitted fixed semantic inks on brand tints and secondary links on fixed
  identity tints. Both validators cover these actual pairs; dark default tint alphas
  and shared golden values now match the expanded contract. Fixed status colours
  and staff accent tokens remain inherited.
- An in-flight theme save could invalidate the destination tenant after navigation.
  The mutation carries the submitted tenant ID/slug/theme snapshot, invalidates that
  tenant, and clears stale mutation feedback when the selected tenant changes.
- A save could overwrite unrelated theme settings before the settings query supplied
  its data. The form now prevents submission until settings exist.
- Invalid-palette previews silently showed product colours with candidate ratios.
  Each fallback preview now explicitly explains which colours and ratios it shows.
- Tests exercised superadmin writes only. Added membership-only manager success,
  cross-tenant refusal, inventory-manager refusal, actor/audit assertions, fallback
  preservation and real member-card contrast regressions.
- The source map omitted the new contrast module, editor and CSS split. Updated it
  and moved its frontend section to SOURCE-MAP-FRONTEND.md, keeping both documents
  under the task's 300-line ceiling without dropping any existing ownership notes.

Verification performed in this review:
- Python py_compile: all 8 changed/new backend Python files compiled successfully.
- npx.cmd tsc -b: passed (the .cmd shim avoids PowerShell execution-policy blocking).
- npx.cmd vitest run: 9 files, 53 tests passed; areas include colour maths, public
  inventory, public events/request panel, printing, member area/directory and editor.
- npx.cmd vite build and node scripts/verify-pwa-build.mjs: passed; the emitted CSS
  compiles the opaque tint utilities, and PWA assets were verified.
- git diff --check, UTF-8/LF and <=300-line checks: passed for all lane files.
  The previous lane files already had LF; no CRLF defect was found.
- No backend pytest or database test ran. These results do not validate database
  execution or browser colour contrast; the coordinator must run those gates.

Tests added in this review:
- backend/tests/makerspaces/test_theme_contrast.py:
  test_bootstrap_colour_fallback_preserves_valid_mode_and_logo_without_writing;
  test_space_manager_can_update_only_their_own_theme_and_audits_the_actor;
  test_inventory_manager_cannot_update_a_theme;
  test_links_and_semantic_inks_remain_readable_on_member_card_tints;
  test_secondary_tints_have_an_opaque_base_for_nested_member_cards.
  Extended the existing CSS/frontend contract guard to pin the fixed semantic inks.
- frontend/src/lib/brandColours.test.ts: six malformed stored-value cases;
  secondary links on fixed identity tints and semantic inks on brand tints.
- frontend/src/features/staff/MakerspaceThemeSettings.test.tsx: unavailable settings
  block writes; malformed colour repair; submitted-tenant invalidation after navigation;
  explicit product-fallback preview label.
- frontend/src/features/members/MemberDirectory.test.tsx: neutral profile base for
  nested identity cards and absence of stacked brand tint containers.

Coordinator backend test paths (not run here):
- backend/tests/makerspaces/test_theme_contrast.py
- backend/tests/makerspaces/test_theme_config.py
- backend/tests/makerspaces/test_makerspace_settings_contract.py
- backend/tests/test_frontend_theme_contrast.py
- backend/tests/test_platform_bootstrap.py

Remaining: coordinator backend tests, OpenAPI snapshot/client regeneration,
independent CLI review gate and owner browser/visual accessibility QA. codex doctor
was rechecked: configuration/home resolution and provider reachability fail in this
sandbox. No separate CLI gate could run; this requested review was performed directly.
No new routes, model fields, models, migrations, environment variables, feature/module
keys, tasks, fan-out or object writers exist in this lane, so no new data-export,
tenant-migration catalog/projection/authority or gate_policy declarations are needed.
The existing settings PATCH remains RBAC-scoped and audited; typed contrast 400s are
covered by its drf-spectacular schema. Generated schema/client files were untouched.

Skipped: footer hiding, as directed (managed-tier product decision). No owner decision
blocks colour rendering; footer gating remains an owner question for a separate lane.
Outside task: malformed restored branding_config can still break bootstrap's dict
merge; this pre-existing support/branding-shape issue was not changed here.

Complete created/modified file inventory for coordinator:
- LANE-PROGRESS.md
- backend/apps/admin_api/serializers_makerspace_validation.py
- backend/apps/admin_api/serializers_theme.py
- backend/apps/admin_api/views_makerspaces.py
- backend/apps/makerspaces/models.py
- backend/apps/makerspaces/platform.py
- backend/apps/makerspaces/theme_contrast.py
- backend/apps/makerspaces/theme_validation.py
- backend/tests/makerspaces/test_theme_contrast.py
- docs/SOURCE-MAP-FRONTEND.md
- docs/SOURCE-MAP.md
- frontend/src/features/inventory/BorrowRequestCard.tsx
- frontend/src/features/inventory/EventRegistrationForm.tsx
- frontend/src/features/inventory/ProductQuickViewModal.tsx
- frontend/src/features/inventory/PublicEventFeedbackPage.tsx
- frontend/src/features/inventory/PublicEventsPage.tsx
- frontend/src/features/inventory/PublicEvidenceUpload.tsx
- frontend/src/features/inventory/PublicInventoryBranding.test.tsx
- frontend/src/features/inventory/PublicInventoryPage.tsx
- frontend/src/features/inventory/PublicSelfCheckoutPage.tsx
- frontend/src/features/inventory/PublicToolScanPanel.tsx
- frontend/src/features/members/MemberArea.tsx
- frontend/src/features/members/MemberAreaBranding.test.tsx
- frontend/src/features/members/MemberDirectory.test.tsx
- frontend/src/features/members/MemberDirectory.tsx
- frontend/src/features/printing/PublicPrintRequestForm.tsx
- frontend/src/features/staff/MakerspaceBrandingSettings.tsx
- frontend/src/features/staff/MakerspaceThemeSettings.test.tsx
- frontend/src/features/staff/MakerspaceThemeSettings.tsx
- frontend/src/features/staff/panels/shared.tsx
- frontend/src/index.css
- frontend/src/lib/brandColours.test.ts
- frontend/src/lib/brandColours.ts
- frontend/src/lib/useTenantBranding.ts
- frontend/src/styles/components.css
- frontend/tailwind.config.ts
- w5-theme-PROGRESS.md
