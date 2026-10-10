# Research Wave 0 ? platform/frontend

Completed D8, D15 (generated first-run credentials only), D16 and D17. Every change is
unstaged inside `research/w0-platform`; no git state-changing commands were run.

## Completed

- D8: closed server-side theme JSON validation for API serializers and model clean/control
  forms; request schema and write error responses. Public/member pages apply AA-guarded
  secondary fill/ink CSS variables. Staff, status, fixed fill text and focus tokens retain
  their palette. Runtime checks cover actual light/dark surfaces and 10%/15% tinted backgrounds and 80% opacity counter text;
  malformed legacy values and insufficient contrast independently restore default tokens.
  Public footers and member screens render safe support links from the bootstrap response.
- D15: setup_instance generates a cryptographic 32-character credential, prints it once on
  new-user creation, and retains required first-login rotation. Re-runs preserve credentials;
  supplied credentials are not printed. Removed the shared-password text from runtime docs
  and explanatory comments. README's existing module and hosting/access content moved into
  two linked reference docs to meet the requested file ceiling; content and links preserved.
- D16: OS colour preference applies before React mounts and follows OS changes until an
  explicit choice. Storage never records an implicit OS default. Both toggle variants share
  the document theme; storage failures and cross-tab changes are handled. Real-stack axe
  coverage now exercises light and dark catalogue, event and booking pages/forms, joining,
  member login and active member screens, staff login and eight main staff panels.
- E2E fixtures: seed_e2e now enables events/bookings/membership and creates a public workshop,
  public bench and branding/support settings; the member email is verified for member login.
- D17: repaired purge comments and removed the redundant classification import.
- Split makerspace model clean logic into models_makerspace_validation.py before adding
  validation. The Makerspace model and its import paths remain unchanged.

## Verification and remaining coordinator work

Frontend focused Vitest invocation completed with exit 0: 20 assertions across five files,
including the existing archived-payment discoverability regression. Production build, app
TypeScript compilation and E2E TypeScript check completed with exit 0. Changed Python files
were parsed with ast, all touched files are under 300 lines, documentation link targets were
checked, git diff --check is clean, and AGENTS.md/CLAUDE.md remain byte-identical.

No backend tests or real-stack browser tests were run. The coordinator must run:

```bash
./scripts/dev.sh test tests/makerspaces/test_theme_config.py tests/test_password_change.py
./scripts/dev.sh e2e a11y.spec.ts
```

The browser command must regenerate the E2E seed using this lane's checkout. CLI review gates
could not run: codex doctor could not resolve configuration or reach the provider from this
sandbox. The coordinator performs review and database/browser validation before committing.
Frontend dependencies were copied from the main checkout into this worktree's ignored
node_modules; build outputs remain ignored. No files were edited in the main checkout.

## Tests added or changed

`backend/tests/makerspaces/test_theme_config.py` (new):

- test_theme_config_rejects_invalid_shape_and_values (14 parameter cases)
- test_theme_config_accepts_closed_partial_configuration (6 parameter cases)
- test_theme_patch_is_validated_audited_and_shipped
- test_control_model_clean_rejects_invalid_theme
- test_api_serializer_exposes_theme_validation_errors (3 parameter cases)

`backend/tests/test_password_change.py`:

- Added test_setup_instance_generates_distinct_credentials.
- Updated test_setup_instance_default_superadmin_must_change_password to check generated
  credential verification, required rotation and repeat-run non-disclosure/preservation.
- Updated test_setup_instance_explicit_password_does_not_force_change for non-disclosure.
- Updated old shared-password explanatory comments; other regression assertions unchanged.

New frontend unit files and all cases:

- lib/brandColours.test.ts: AA fill/ink application only to public/member secondary tokens;
  independent low-contrast fallbacks; rechecking dark surfaces/fixed fill text; checking tints;
  invalid legacy values and tenant-switch override clearing; 80% counter text (6 cases).
- components/ThemeToggle.test.tsx: follow OS without writing a preference; preserve explicit
  light/dark choices (2 cases); save/share clicks; invalid stored choice/cross-tab change;
  unavailable storage (6 cases total).
- components/SupportContact.test.tsx: public-footer links; hidden empty configuration;
  rejected javascript/data/credential-bearing legacy URLs (5 cases total).
- features/members/MemberAreaBranding.test.tsx: member contact links and locally scoped CSS
  variables (1 case). Existing MemberAreaArchivedLink.test.tsx was run unchanged (2 cases).

`frontend/e2e/a11y.spec.ts` (changed; 13 scenarios in each of light/dark, 26 total):

- public catalogue and support footer; staff login; staff requests console;
- public events + expanded registration form; public bookings + expanded request form;
- member joining screen + sign-in + active membership area;
- staff dashboard, inventory, members, machines, events, bookings and settings panels.

## Migrations, skipped scope, decisions and outside defects

No migrations, new models, feature keys or module keys. No migration dependencies apply.
MFA is excluded explicitly by the task (Wave 1). Generated OpenAPI artifacts were not
regenerated, as instructed; the coordinator must regenerate them. No owner decisions remain
for this scope. Outside-scope documentation defect noticed: docs/SOURCE-MAP.md still assigns checkout,
webhooks and native payment intents to apps/payments rather than apps/payments_rail;
the existing payments paragraph was left unchanged. No additional code defect was identified.
Historical research notes in the main checkout were read only and remain unchanged.

## File inventory

### Created

- `LANE-PROGRESS.md`
- `backend/apps/admin_api/serializers_theme.py`
- `backend/apps/makerspaces/models_makerspace_validation.py`
- `backend/apps/makerspaces/theme_validation.py`
- `backend/apps/operations/management/commands/_seed_e2e_discovery.py`
- `backend/tests/makerspaces/test_theme_config.py`
- `docs/README-HOSTING.md`
- `docs/README-MODULES.md`
- `frontend/src/components/SupportContact.test.tsx`
- `frontend/src/components/SupportContact.tsx`
- `frontend/src/components/ThemeToggle.test.tsx`
- `frontend/src/features/members/MemberAreaBranding.test.tsx`
- `frontend/src/lib/brandColours.test.ts`
- `frontend/src/lib/brandColours.ts`
- `frontend/src/lib/theme.ts`
- `frontend/src/lib/useTenantBranding.ts`

### Modified

- `README.md`
- `backend/apps/accounts/permissions.py`
- `backend/apps/admin_api/permissions.py`
- `backend/apps/admin_api/serializers_makerspace_validation.py`
- `backend/apps/admin_api/serializers_makerspaces.py`
- `backend/apps/admin_api/views_makerspaces.py`
- `backend/apps/data_export/classification.py`
- `backend/apps/makerspaces/lifecycle_purge.py`
- `backend/apps/makerspaces/management/commands/setup_instance.py`
- `backend/apps/makerspaces/models_makerspace.py`
- `backend/apps/operations/management/commands/seed_e2e.py`
- `backend/config/admin_access.py`
- `backend/tests/test_password_change.py`
- `docs/PROJECT-STATUS.md`
- `docs/SOURCE-MAP.md`
- `frontend/e2e/a11y.spec.ts`
- `frontend/e2e/helpers.ts`
- `frontend/src/components/SiteFooter.tsx`
- `frontend/src/components/ThemeToggle.tsx`
- `frontend/src/features/bookings/PublicBookingsPage.tsx`
- `frontend/src/features/inventory/PublicEventFeedbackPage.tsx`
- `frontend/src/features/inventory/PublicEventsPage.tsx`
- `frontend/src/features/inventory/PublicInventoryPage.tsx`
- `frontend/src/features/inventory/PublicMachinesPage.tsx`
- `frontend/src/features/inventory/PublicSelfCheckoutPage.tsx`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/printing/PublicPrintRequestPage.tsx`
- `frontend/src/features/staff/ChangePasswordGate.tsx`
- `frontend/src/features/stats/PublicStatsPage.tsx`
- `frontend/src/lib/branding.ts`
- `frontend/src/main.tsx`

