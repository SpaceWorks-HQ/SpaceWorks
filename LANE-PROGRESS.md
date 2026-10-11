# w7-events handoff

Scope complete: BUILD GAPS WP1 items 1-4 and WP2 item 6, events half only.
Every edit is inside this worktree and unstaged. No git state-changing commands ran.

Completed behavior:
- Opt-in accounts/invite audiences; members remains the migration default.
- Event-bound keyed invite/promotional digests, one-time disclosure, limits/expiry/revocation,
  uniform invalid-code 404, audited and atomic redemption under the event lock.
- Ticket tiers with member/public prices, sales windows and per-type/event capacity.
  Membership off/inactive hides and refuses member tiers; no free fallback when tiers exist.
- Registration freezes admission audience, amount and discount. Existing ticket QR/cancel
  access survives event/series audience edits. Waitlist/approval use the original quote.
- Series creation copies independent ticket templates into occurrences.
- Record-first ledger charging works without the rail; a local ledger error rolls back
  registration/code use. Provider failures retain the charge. Offline payment uses ManualSettlement.
- Categories/tags, public detail API/component, tier-aware prices, filters, share metadata,
  tenant-authenticated calendar transport, public/staff/partner code and ticket entry.
- Account contact fallbacks preserve account-authoritative contact/identity and never authorize invites.
- Organizer-only staff can create/list/revoke codes for their exact organized events.
- Events membership dependency/profile removed; bookings remains another lane's responsibility.
- New model classification/datasets, field snapshot, target inert credential reset, audit-ID remapping,
  independent authority pins, module purge/origin/API-client registry and OpenAPI annotations.
- Admin registration serializers split behind explicit re-exports; all touched code is <=300 lines.

Migration:
- backend/apps/events/migrations/0025_event_ticketing_and_audience.py
- Dependencies: events.0024_event_cancellation_policy (actual previous leaf, listed before creation).
- Creates EventInvite/EventPromoCode/EventTicketType/EventCategory and adds audience/category/tags,
  registration admission provenance, selected references and quote/discount fields.

Validation performed:
- Vitest: 13 targeted files, 39 passed, 0 failed (final full targeted run).
- tsc -b: only the five owner-listed pre-existing error areas; no lane errors.
- AST syntax checks pass for every touched Python file; no touched code file exceeds 300 lines.
- git diff --check passes; AGENTS.md and CLAUDE.md remain byte-identical and unchanged.
- Read-only reviewer completed a second pass with no remaining blocking findings.
- No backend/database tests ran. Django is unavailable here; Docker/Postgres access is prohibited.
- ESLint is not a project dependency or script; the attempted optional invocation was unavailable.
- codex doctor could not reach CLI config/provider; coordinator owns unavailable nested CLI gates.

Coordinator work still required:
- Run ./scripts/dev.sh test tests/events tests/modules tests/makerspaces/test_module_registry.py
  tests/test_apiclient_scope_registry.py tests/data_export tests/tenant_migration tests/separability.
  Run one disposable test invocation at a time; no shared DB/concurrent full-suite review.
- Run TOMBSTONED_APPS=payments_rail ./scripts/dev.sh test tests/modules/test_family_events_only.py.
  The same three free/invite/paid HTTP cases are deliberately reused under the physical rail tombstone.
- Run Django system/migration drift checks and regenerate merged catalog SHA256 (not repinned here).
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts after all lanes merge.
- WP2 mounts PublicEventDetailPage at /m/:slug/events/:publicToken and /events/:publicToken.
  AppRoutes.tsx was intentionally left to WP2 as required by the audit's cross-package ordering.
- Stage/commit/merge/push only through the coordinator/owner; this lane performed none.

Skipped by explicit scope/owner deferral:
- Guest/no-account registration, waitlist offer windows, automatic refunds, paid-cancel re-registration,
  event-to-certification binding, booking independence, loans switch/public-home routing and other packages.
- No additional owner product decision is needed for this lane.

Outside-task defects observed:
- tests/modules/test_combo_profiles.py still omits maintenance -> machines in the exact dependency pin.
  WP2 item 5 owns that correction; this lane only removes the events dependency/profile count.
- docs/README-MODULES.md retains the stale events profile size/dependency material; WP2 owns its refresh.
- The five known TypeScript areas remain unchanged: generated/api.ts, MemberPayments.test.tsx,
  MembersPanel.tsx, PaymentBilling.test.tsx and panels/OrganizedEventsPanel.test.tsx.

Tests added or updated (unrun backend tests must be run by coordinator):
- backend/tests/events/test_account_ticket_access.py:
  - test_account_ticket_ownership_survives_audience_edits_without_opening_member_history
  - test_account_only_ticket_does_not_authorize_a_member_default_registration
- backend/tests/events/test_concurrent_event_redemptions.py:
  - test_concurrent_last_code_use_has_one_winner_and_no_orphan_registration
- backend/tests/events/test_event_categories_and_detail.py:
  - test_public_detail_categories_and_tags_do_not_expose_private_registration_data
  - test_public_detail_enumeration_safe_404
  - test_module_off_detail_returns_400_and_foreign_category_is_refused
  - test_staff_category_create_is_scoped_and_audited
- backend/tests/events/test_event_invites.py:
  - test_invite_is_digest_only_email_bound_and_idempotent_retry_does_not_spend_use
  - test_bad_invites_have_uniform_404_and_do_not_register
  - test_staff_invites_are_tenant_scoped_and_codes_are_returned_once
  - test_failed_form_validation_does_not_consume_an_invite
- backend/tests/events/test_promo_codes.py:
  - test_promo_modifies_real_charge_and_audits_once
  - test_promo_limits_and_scoping_are_uniform_and_atomic
  - test_waitlisted_discount_survives_expiry_and_is_used_on_charge_creation
  - test_promo_redemption_is_bounded_by_registration_throttle
  - test_staff_promo_create_list_and_revoke_hide_secret_and_cross_tenant
  - test_named_promo_can_be_reused_on_another_event_but_not_duplicated_here
- backend/tests/events/test_public_event_leaks.py:
  - test_openapi_has_exact_public_contracts_and_documented_errors
- backend/tests/events/test_registration_audience.py:
  - test_accounts_audience_works_with_no_membership_or_payment_module
  - test_members_default_still_requires_membership_and_anonymous_is_refused
  - test_accounts_registration_cannot_bypass_account_standing
  - test_staff_can_register_an_account_without_inventing_a_membership
  - test_collaborative_service_still_requires_a_member_of_the_collaborating_space
  - test_audience_feature_off_refuses_and_module_off_is_400
  - test_account_signup_with_missing_contact_can_supply_a_fallback
  - test_contact_fallback_cannot_replace_account_identity_or_bind_an_invite
- backend/tests/events/test_ticket_types.py:
  - test_member_price_public_price_and_membership_off_degrade
  - test_per_type_capacity_fifo_and_price_snapshot_survive_promotion
  - test_promotion_skips_a_full_type_and_respects_event_capacity
  - test_sales_window_hides_and_refuses_type
  - test_series_materialization_copies_independent_ticket_templates
  - test_idempotent_registration_retry_survives_closed_ticket_sales
  - test_membership_off_with_only_member_types_cannot_fall_back_to_free
  - test_ledger_failure_rolls_back_paid_registration_and_code_redemption
  - test_optional_checkout_failure_keeps_the_recorded_charge
  - test_approval_uses_frozen_discount_and_type_capacity
- backend/tests/events/test_ticketing_authority_and_collaboration.py:
  - test_organization_event_manager_can_revoke_only_its_own_event_codes
  - test_collaborative_discovery_exposes_eligible_tickets_and_registration_uses_codes
- backend/tests/events/test_ticketing_export_contract.py:
  - test_event_ticketing_models_have_literal_export_and_projection_classification
  - test_code_and_contact_digests_never_export_and_get_fresh_target_defaults
  - test_imported_event_codes_are_revoked
- backend/tests/makerspaces/test_module_registry.py:
  - test_events_is_independent_of_membership
- backend/tests/modules/test_combo_profiles.py:
  - test_the_published_module_dependencies
- backend/tests/modules/test_family_events_only.py:
  - test_events_only_create_publish_detail_register_offline_settle_checkin
- backend/tests/modules/test_offstate_facilities.py:
  - test_events_either_declares_membership_or_works_when_membership_is_off
- backend/tests/test_apiclient_scope_registry.py:
  - test_legacy_cutover_is_explicit_and_new_entries_default_to_excluded
  - test_event_detail_requires_explicit_public_scope
- frontend/src/features/events/EventPrice.test.tsx:
  - shows paid tier price even when the legacy amount is zero
  - shows range starting at free when there is a free tier
  - does not advertise a free fallback when member tiers are unavailable
- frontend/src/features/events/EventTicketPicker.test.tsx:
  - shows only server-authorized prices and lets a full type join the waitlist
  - renders a free member ticket when the server includes it
- frontend/src/features/inventory/PublicEventDetailPage.test.tsx:
  - renders share metadata and sends invite, ticket and promo in registration
  - shows an enumeration-safe missing event
  - downloads calendar using configured tenant API transport
  - blocks registration when only unavailable member tickets exist
  - requests missing contact fields and retries the same account registration
- frontend/src/features/inventory/PublicEventsPage.test.tsx:
  - filters by tenant category and tag and links each event detail
- frontend/src/features/members/PartnerEventsTicketing.test.tsx:
  - collects the required ticket and invitation and submits optional promo
- frontend/src/features/staff/EventFormFields.test.tsx:
  - keeps comma-separated tag entry editable and trims tags at submission
- frontend/src/features/staff/EventInvitesPanel.test.tsx:
  - creates a bounded invitation, reveals its code once and revokes it
  - shows failure without revealing a code
- frontend/src/features/staff/EventPromosPanel.test.tsx:
  - creates a fixed discount with a named code and hides the one-time result
- backend/tests/events/ticketing_helpers.py supplies events-only account fixtures.
- backend/tests/tenant_migration/authority_expectations_w7_events.py adds five independent RESET pins,
  unioned in authority_expectations_d8.py for test_authority_dispositions_d8.py.

Complete created/modified file manifest (A = created, M = modified):
- A LANE-PROGRESS.md
- M backend/apps/apiclients/scope_registry_routes.py
- M backend/apps/data_export/classification.py
- A backend/apps/data_export/classification_w7_events.py
- M backend/apps/data_export/datasets.py
- A backend/apps/data_export/datasets_w7_events.py
- M backend/apps/data_export/fields.py
- M backend/apps/data_export/references_core.py
- M backend/apps/events/capacity.py
- A backend/apps/events/invites.py
- A backend/apps/events/migrations/0025_event_ticketing_and_audience.py
- M backend/apps/events/models.py
- A backend/apps/events/models_categories.py
- M backend/apps/events/models_event.py
- A backend/apps/events/models_invites.py
- A backend/apps/events/models_promos.py
- M backend/apps/events/models_registration.py
- M backend/apps/events/models_series.py
- A backend/apps/events/models_tickets.py
- A backend/apps/events/participant_access.py
- A backend/apps/events/promos.py
- A backend/apps/events/registration_access.py
- M backend/apps/events/serializers_admin.py
- M backend/apps/events/serializers_collaborators.py
- M backend/apps/events/serializers_public.py
- A backend/apps/events/serializers_registration_admin.py
- M backend/apps/events/serializers_series.py
- A backend/apps/events/serializers_ticketing.py
- A backend/apps/events/serializers_ticketing_public.py
- M backend/apps/events/service_payments.py
- M backend/apps/events/services.py
- M backend/apps/events/services_registration.py
- M backend/apps/events/services_registration_state.py
- M backend/apps/events/services_series.py
- A backend/apps/events/ticketing.py
- M backend/apps/events/urls_admin.py
- M backend/apps/events/urls_public.py
- A backend/apps/events/urls_ticketing.py
- M backend/apps/events/views_admin_registrations.py
- M backend/apps/events/views_checkin.py
- A backend/apps/events/views_invites.py
- M backend/apps/events/views_member_events.py
- M backend/apps/events/views_public.py
- A backend/apps/events/views_public_detail.py
- M backend/apps/events/views_registration_cancel.py
- A backend/apps/events/views_ticketing.py
- M backend/apps/makerspaces/capability_definitions.py
- A backend/apps/makerspaces/capability_definitions_w7_events.py
- M backend/apps/makerspaces/module_profiles.py
- M backend/apps/makerspaces/module_purge_collectors.py
- M backend/apps/makerspaces/module_registry_catalog.py
- M backend/apps/makerspaces/origin_scope_routes.py
- A backend/apps/makerspaces/origin_scope_routes_w7_events.py
- M backend/apps/tenant_migration/audit_references_meta.py
- A backend/apps/tenant_migration/catalog_w7_events.py
- M backend/apps/tenant_migration/target_projection_fields.py
- A backend/apps/tenant_migration/target_projection_w7_events.py
- M backend/apps/tenant_migration/tenant_dump_authority.py
- M backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- M backend/apps/tenant_migration/tenant_dump_model_catalog.py
- A backend/tests/events/test_account_ticket_access.py
- A backend/tests/events/test_concurrent_event_redemptions.py
- A backend/tests/events/test_event_categories_and_detail.py
- A backend/tests/events/test_event_invites.py
- A backend/tests/events/test_promo_codes.py
- M backend/tests/events/test_public_event_leaks.py
- A backend/tests/events/test_registration_audience.py
- A backend/tests/events/test_ticket_types.py
- A backend/tests/events/test_ticketing_authority_and_collaboration.py
- A backend/tests/events/test_ticketing_export_contract.py
- A backend/tests/events/ticketing_helpers.py
- M backend/tests/makerspaces/test_module_registry.py
- M backend/tests/modules/test_combo_profiles.py
- A backend/tests/modules/test_family_events_only.py
- M backend/tests/modules/test_offstate_facilities.py
- M backend/tests/tenant_migration/authority_expectations_d8.py
- A backend/tests/tenant_migration/authority_expectations_w7_events.py
- M backend/tests/test_apiclient_scope_registry.py
- M docs/INVARIANTS.md
- M docs/MODULES-WORKSHOPS.md
- M docs/MODULES.md
- M docs/SOURCE-MAP-DOMAINS.md
- A frontend/src/features/events/EventContactFallback.tsx
- A frontend/src/features/events/EventPrice.test.tsx
- M frontend/src/features/events/EventPrice.tsx
- A frontend/src/features/events/EventTicketPicker.test.tsx
- A frontend/src/features/events/EventTicketPicker.tsx
- A frontend/src/features/events/eventCalendar.ts
- A frontend/src/features/events/eventTicketTypes.ts
- M frontend/src/features/inventory/EventRegistrationForm.tsx
- A frontend/src/features/inventory/PublicEventDetailPage.test.tsx
- A frontend/src/features/inventory/PublicEventDetailPage.tsx
- M frontend/src/features/inventory/PublicEventsPage.test.tsx
- M frontend/src/features/inventory/PublicEventsPage.tsx
- M frontend/src/features/members/PartnerEvents.tsx
- A frontend/src/features/members/PartnerEventsTicketing.test.tsx
- A frontend/src/features/staff/EventCategoriesField.tsx
- M frontend/src/features/staff/EventDrawer.tsx
- M frontend/src/features/staff/EventFormFields.test.tsx
- M frontend/src/features/staff/EventFormFields.tsx
- A frontend/src/features/staff/EventInvitesPanel.test.tsx
- A frontend/src/features/staff/EventInvitesPanel.tsx
- A frontend/src/features/staff/EventPromosPanel.test.tsx
- A frontend/src/features/staff/EventPromosPanel.tsx
- M frontend/src/features/staff/EventRegisterMember.tsx
- M frontend/src/features/staff/EventRegistrationRoster.tsx
- M frontend/src/features/staff/EventSeriesForm.tsx
- A frontend/src/features/staff/EventStaffTicketPicker.tsx
- A frontend/src/features/staff/EventTicketTemplates.tsx
- A frontend/src/features/staff/EventTicketsPanel.tsx
- M frontend/src/features/staff/eventSeriesApi.ts
- A frontend/src/features/staff/eventTicketingApi.ts
- M frontend/src/features/staff/eventsApiTypes.ts
- M frontend/src/features/staff/eventsRegistrationApi.ts
- M frontend/src/lib/features.ts

## Review pass (2026-10-11)

Reviewed AGENTS.md, the original brief, this handoff, the full tracked diff and added
files, the BUILD GAPS section (including package ordering and owner deferrals),
00-index.md, events-bookings.md, relevant invariants and the dev/global workflow.
Git remained read-only: no staging, commits, branch changes, merges or pushes.

Defects found and fixed:
1. Contact fallback could reveal another attendee's registration status or take over
   their cancelled registration. The transactional service now refuses an email match
   unless the identified account owns that exact row. HTTP regressions cover both live
   and cancelled rows and prove no ownership/status change or status disclosure.
2. New invite/promo/ticket models lacked tenant-owner validation. Model.clean now checks
   that the event/series belongs to the row's makerspace; tickets require exactly one
   owner. Public ticket selection also filters the owning makerspace. Model regressions
   exercise foreign event/series owners and ambiguous ownership.
3. Materialized ticket copies had no individual audit evidence. Each occurrence copy now
   records event.ticket_created in its creation transaction, with the initiating actor
   (or the background task's null actor). A real two-occurrence creation test checks it.
4. Event checkout/cancellation logger.exception calls could print provider exception
   strings containing credentials or signed URLs. Logs now use constant messages plus
   payment/registration IDs, without exception text/tracebacks. Tests inject secret
   canaries into scheduling, the actual post-commit checkout callback and cancellation;
   they check logs and that the recorded charge survives.
5. Audience/provenance and ticket eligibility inputs had no explicit migration authority
   decisions. Added five literal PRESERVE declarations and independent expectation pins:
   Event/EventSeries/EventRegistration.registration_audience and EventTicketType.audience/
   is_active. They preserve tenant content/history while requiring live target gates and
   membership proof. The five credential RESET declarations remain intact.
6. EventEligibleMemberSerializer accidentally included registration-only invite/promo/
   ticket input fields. Removed them. Completed missing errors on touched roster,
   eligible-member and attendance operations, documented the new staff lists' page
   parameter and field-keyed 400 errors, and extended generated-schema assertions for
   the detail and ticketing routes and exact picker response.
7. Staff account-ID entry retained the previous attendee's fallback contact/codes/ticket,
   while still querying a membership roster and displaying misleading member messaging.
   Account audiences now use one account input without the member-roster query; changing
   either kind of attendee clears contact, ticket and code state. Vitest verifies the
   second POST has only the new account ID and no previous contact.
8. Navigating between public details or staff drawers could retain success/form/secret
   state from the previous event. Keyed public registration forms by tenant/event and
   staff roster/ticketing panels by event ID. The navigation test registers for one
   event, follows a link to another and verifies a fresh form.
9. A refused detail refetch could still render the cached event and registration form.
   The page now hides cached content on error; a test starts with loaded data, forces a
   real QueryClient refetch to 404 and verifies the form disappears.
10. The free-event filter treated unavailable member-only tiers as a free legacy event.
    It now excludes events requiring a ticket when this account has no eligible types.
    Vitest verifies an eligible free public event remains visible.
11. LF-only hygiene had not been met: 99 touched files contained CRLF. Normalized these
    files to UTF-8/LF without changing AGENTS.md or CLAUDE.md. Root docs/SOURCE-MAP.md now
    also indexes the lane's access, public-detail and staff-ticketing entry points.
12. Missing negative coverage for revoked membership pricing is now exercised through
    authenticated public detail and registration: the public tier remains visible and
    the member tier is refused without creating a registration.

Review validation:
- python -m py_compile: all 78 touched backend Python files passed.
- npx.cmd vitest run: 12 targeted files, 32 tests passed, zero failures. Includes the
  event price/picker, public list/detail, staff fields/series/register/roster/codes,
  registration API and partner ticketing tests, including four new frontend regressions.
- npx.cmd tsc -b: no lane errors; only the five brief-listed existing error areas remain
  (generated/api.ts, MemberPayments.test.tsx, MembersPanel.tsx, PaymentBilling.test.tsx,
  panels/OrganizedEventsPanel.test.tsx). npx.cmd was necessary because PowerShell blocks
  npx.ps1 under the current execution policy.
- git diff --check passed; no touched CRLF, detected mojibake or code files over 300
  lines; AGENTS.md and CLAUDE.md remain byte-identical and unchanged.
- Migration 0025 still chains from the actual prior events leaf 0024. New models retain
  literal export/dataset/catalog/field declarations and introduce no accounts.User FKs.
- No new environment variables, tasks, cross-tenant fan-out entry points or object-storage
  writers were introduced. Existing series-task gate participation still covers ticket
  materialization. New HTTP mutations resolve through the registered origin/source-gate
  routes and staff RBAC event/makerspace helpers.
- Backend/database tests and schema generation remain unrun: Django is not installed in
  this environment. codex doctor again failed config/home resolution and provider
  reachability; nested CLI review gates remain coordinator work, not reported as passed.

New review test file:
- backend/tests/events/test_ticketing_review_regressions.py (11 parametrized cases):
  contact ownership/status confidentiality, tenant/series-owner validation, individual
  ticket-copy audit rows, revoked member pricing and credential-safe payment error logs.

Additional files touched by this review beyond the original manifest:
- A backend/tests/events/test_ticketing_review_regressions.py
- M frontend/src/features/staff/EventRegisterMember.test.tsx
- M docs/SOURCE-MAP.md
Other fixes and tests are in files already listed in the original manifest.

Coordinator must run these backend paths with the disposable runner after integration:

```bash
./scripts/dev.sh test tests/events tests/modules tests/makerspaces/test_module_registry.py tests/test_apiclient_scope_registry.py tests/data_export tests/tenant_migration tests/separability
TOMBSTONED_APPS=payments_rail ./scripts/dev.sh test tests/modules/test_family_events_only.py
```

The new review regressions and expanded OpenAPI checks are included in tests/events;
run tests/tenant_migration/test_authority_dispositions_d8.py as part of the migration
suite to validate the five additional independent authority pins. Do not run database
suites concurrently. The original coordinator obligations to run Django migration/system
checks, recompute the merged catalog SHA256, regenerate the OpenAPI snapshot/client and
mount the public detail page in WP2 remain. The WP2-owned maintenance dependency pin and
README profile documentation drift remain outside this lane as specified by the audit.
