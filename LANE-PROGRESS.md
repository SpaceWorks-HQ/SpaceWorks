# w6-packs progress

Implementation complete; all changes are unstaged on lane/w6-packs.

Completed: version-1 SHA-256 configuration packs, strict field/type validation,
RBAC-scoped export and dry-run diff, preview checksum conflict handling, atomic
audited apply through domain writers, active-waiver publication without rewriting
history, and superadmin platform profiles applied in the makerspace creation
transaction. Frontend export/editor/download/preview/apply and creation profile
picker are wired through handwritten API calls.

Boundary: no identities, members, debts, payment rows, evidence, audit history,
credentials, routing, stock quantities, edition override or machine scope grants.
Feature packs.import defaults off. Modules remain superadmin-only. Imports upsert
configuration and retain absent entries. Profiles are named create-only snapshots.

Self-review fixes: admission modes and disabled feature switches preserved;
reference plan amounts converted to Decimal; retained unavailable notification
channels omitted; waiver version/history protected; HTTP versions not coerced;
template whitespace/empty bodies preserved; role identities follow case-insensitive
authority; noncanonical coercions refused; saved presets require reference closure;
platform admin and source-gate declarations added; creation errors documented;
explicit default loan policies distinguished from unconfigured legacy defaults.

Migration: backend/apps/makerspaces/migrations/0082_space_pack_profile.py
depends on makerspaces.0081_makerspace_loan_policy (actual predecessor checked).
SpacePackProfile is OMITTED in data_export and consequently DROP in tenant dump
model catalog, has a literal field snapshot, and intentionally has no User FKs.

Static validation: TypeScript compiler exited 0; changed Python ASTs parse;
git diff --check reports no whitespace defects; changed files are UTF-8/LF,
under 300 lines, and have no detected mojibake. AGENTS.md/CLAUDE.md stay identical.
Preexisting feature definitions and relocated SOURCE-MAP content were checked
for preservation. No database tests or frontend tests were executed; no test
result is claimed. Local Python has no Django. codex doctor cannot load CLI
configuration or reach its provider, so independent CLI review remains blocked.

Coordinator remaining work: run isolated database tests and frontend tests below,
plus classification/tenant catalog, source gate, admin scoping and feature guards;
regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts;
review/QA and commit. This lane deliberately did not change generated artifacts.

Owner decisions: none needed to use this implementation. Self-serve module
installation and per-makerspace editions remain deferred as the brief requires.

Outside-task defect: backend/tests/test_capabilities.py line 16 pins 19 features;
HEAD already defines 28 (this lane adds one, making 29). This is a preexisting
stale assertion, not a claimed test result. Left for the coordinator because the
file exceeds the lane ceiling and changing it requires a separate test split.

Suggested coordinator commands (not run here):
```bash
./scripts/dev.sh test tests/makerspaces/test_space_pack_format.py tests/makerspaces/test_space_pack_services.py tests/makerspaces/test_space_pack_api.py tests/makerspaces/test_space_pack_openapi.py
./scripts/dev.sh test tests/test_admin_hidden_scope.py tests/data_export tests/tenant_migration tests/makerspaces/test_module_registry.py tests/test_capabilities.py
cd frontend
npm test -- src/features/staff/SpacePacksPanel.test.tsx
```

## Complete file manifest

- `LANE-PROGRESS.md`
- `backend/apps/admin_api/serializers_makerspace_mutations.py`
- `backend/apps/admin_api/serializers_makerspaces.py`
- `backend/apps/admin_api/serializers_space_packs.py`
- `backend/apps/admin_api/urls_makerspaces.py`
- `backend/apps/admin_api/views_loan_policy.py`
- `backend/apps/admin_api/views_makerspaces.py`
- `backend/apps/admin_api/views_space_packs.py`
- `backend/apps/data_export/classification_platform.py`
- `backend/apps/data_export/references_core.py`
- `backend/apps/data_export/space_pack_configuration.py`
- `backend/apps/makerspaces/admin.py`
- `backend/apps/makerspaces/admin_space_packs.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/makerspaces/capability_definitions.py`
- `backend/apps/makerspaces/loan_policy_settings.py`
- `backend/apps/makerspaces/migrations/0082_space_pack_profile.py`
- `backend/apps/makerspaces/models.py`
- `backend/apps/makerspaces/models_space_packs.py`
- `backend/apps/makerspaces/module_install.py`
- `backend/apps/makerspaces/space_pack_export.py`
- `backend/apps/makerspaces/space_pack_format.py`
- `backend/apps/makerspaces/space_pack_mutations.py`
- `backend/apps/makerspaces/space_pack_prepare.py`
- `backend/apps/makerspaces/space_pack_services.py`
- `backend/apps/makerspaces/space_pack_validation.py`
- `backend/apps/tenant_migration/gate_policy_http.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/config/admin_scope_registry.py`
- `backend/tests/makerspaces/space_pack_helpers.py`
- `backend/tests/makerspaces/test_space_pack_api.py`
- `backend/tests/makerspaces/test_space_pack_format.py`
- `backend/tests/makerspaces/test_space_pack_openapi.py`
- `backend/tests/makerspaces/test_space_pack_services.py`
- `docs/SOURCE-MAP-APPS.md`
- `docs/SOURCE-MAP.md`
- `docs/SPACE-PACKS.md`
- `frontend/src/features/staff/MakerspaceSettingsPanel.tsx`
- `frontend/src/features/staff/SpacePackProfilePicker.tsx`
- `frontend/src/features/staff/SpacePacksPanel.test.tsx`
- `frontend/src/features/staff/SpacePacksPanel.tsx`
- `frontend/src/features/staff/panels/users/forms.ts`
- `frontend/src/features/staff/panels/usersModals/CreateMakerspaceModal.tsx`
- `frontend/src/features/staff/panels/usersModals/types.ts`
- `frontend/src/features/staff/spacePacksApi.ts`
- `frontend/src/lib/features.ts`

## Added tests (coordinator must run)

Shared fixtures: `backend/tests/makerspaces/space_pack_helpers.py`.

`backend/tests/makerspaces/test_space_pack_api.py`:

- `test_space_manager_own_scope_and_suspended_accounts_are_refused`
- `test_hidden_space_is_not_available_to_global_superadmin`
- `test_feature_and_module_off_answer_400_not_404`
- `test_modules_remain_superadmin_only_and_edition_is_not_a_pack_field`
- `test_custom_role_import_enforces_non_escalation_and_protected_roles`
- `test_unknown_version_and_checksum_refusals_do_not_write`
- `test_platform_profiles_are_superadmin_only_paginated_and_not_tenant_dump_data`
- `test_create_makerspace_applies_saved_profile_in_creation_transaction`
- `test_http_protocol_does_not_coerce_unknown_version_types`
- `test_apply_service_refuses_a_frozen_tenant_before_any_write`
- `test_saved_profiles_refuse_missing_references_and_contradictory_policy_aliases`
- `test_admission_import_keeps_existing_editor_bounds`

`backend/tests/makerspaces/test_space_pack_format.py`:

- `test_checksum_is_canonical_and_detects_tampering`
- `test_unknown_versions_are_refused_even_with_checksum`
- `test_extra_envelope_fields_cannot_smuggle_tenant_records`
- `test_pack_projection_is_a_reviewed_subset_of_data_export_without_pii_or_money_models`
- `test_invalid_json_values_and_oversize_are_refused`
- `test_non_ascii_checksum_and_invalid_unicode_are_refused`

`backend/tests/makerspaces/test_space_pack_openapi.py`:

- `test_pack_routes_have_request_response_and_error_schemas`
- `test_profile_model_has_literal_fields_and_no_user_references`

`backend/tests/makerspaces/test_space_pack_services.py`:

- `test_round_trip_all_configuration_sections_and_idempotent_apply`
- `test_dry_run_never_creates_rows_or_audits_or_updates_timestamps`
- `test_atomic_failure_rolls_back_configuration_roles_and_every_audit`
- `test_stale_preview_and_missing_preview_refused_without_changes`
- `test_no_members_money_credentials_evidence_or_history_in_export`
- `test_unknown_item_template_fields_are_rejected_before_apply`
- `test_invalid_booking_bounds_and_missing_references_are_rejected_in_preview`
- `test_duplicate_product_names_refuse_export_and_unrelated_rows_survive_import`
- `test_admission_mode_and_disabled_feature_gates_survive_idempotent_import`
- `test_existing_waiver_version_cannot_be_overwritten_or_reactivated`
- `test_export_omits_retained_notification_channels_with_modules_off`
- `test_template_whitespace_and_empty_email_bodies_round_trip`
- `test_preview_refuses_field_coercion_that_would_hide_actual_written_values`
- `test_explicit_default_loan_policy_is_distinct_from_unconfigured_legacy_defaults`

`frontend/src/features/staff/SpacePacksPanel.test.tsx`:

- requires a preview, sends its checksum on apply and refreshes server state
- invalidates the preview after editing and does not submit malformed JSON
- shows saved profiles only to a superadmin and saves a named snapshot
