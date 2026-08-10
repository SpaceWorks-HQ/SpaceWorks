# Module-architecture program — security and loophole review

**Scope:** everything built in the module-architecture program on `dev` — module groups, the one
staff-tab module map, the `payments`/`accounts`/`mobile`/`updates` keys, the Razorpay provider seam,
the superadmin modules console, the cloud/full deploy profiles, the account-less identity seam and
walk-in records, the four login-method switches, maker profiles and the member directory, and staff
event registration.

**Method:** read the code, then pin each conclusion as an assertion.
`backend/tests/test_module_program_security_p11.py` is this report in executable form — every
"verified" below is a test in that file or in the per-phase suites it names. Prose alone would drift.

**Summary:** no high-severity finding. **One medium availability regression shipped in this program
and is fixed here** (M0). Two further medium items were found and fixed during the build. Four risks
are accepted with reasons. Two are pre-existing and untouched by this program.

---

## Found by this review

### M0 — a makerspace with a narrow module set could be created and then never saved again *(fixed)*

Shipped in `c575763` (the phase that added the `payments`/`accounts`/`mobile`/`updates` keys) and
caught here by running the whole suite rather than the phases' own tests.

`payments.enabled` and `mobile.push` default **on**, and `enabled_features` takes its field default
independently of `enabled_modules`. So a makerspace created with a narrow module list — a `minimal`
profile install, or any `Makerspace.objects.create(enabled_modules=[…])` — was born holding features
whose modules it did not have. `Makerspace.clean()` then raised on **every subsequent save**,
including saves touching neither field: a Space Manager toggling public stats got
`payments.enabled requires payments to be enabled`, a message about a field their request never
mentioned, with no way to act on it from their console.

The phase-3 reasoning ("a direct save stays strict so `/control/` shows a real error") was right about
the goal and wrong about the layer. Fixed by splitting the two:

- **`Makerspace.clean()` normalizes.** It prunes features whose module is absent, exactly as it
  already adds core modules back rather than rejecting a row that lost one. A row cannot be born or
  left inconsistent.
- **The explicit `validate_capabilities` call sites still validate.** The `/control/` capability
  matrix and `module_install` both call it directly before saving, so a conflict an operator actually
  expressed is still reported rather than silently cleared.
- **The staff serializer prunes only when the request does not carry `enabled_features`.** If the
  caller sent features, they expressed the combination and get the error; if they did not, it is not
  their conflict to answer for.

Verified by `test_clean_prunes_an_orphaned_feature_rather_than_refusing`,
`test_the_control_matrix_still_reports_an_orphaned_feature` and
`test_a_narrowly_created_makerspace_can_still_be_saved`. The phase-3 test that pinned the old rule was
rewritten rather than deleted, so the reversal is on the record.

**Process note:** this is the argument for the audit phase existing. Each phase ran the suites it
touched and was green; the regression only appeared in a full run, four commits later, in a file
neither phase named.

---

## Found by the Codex Stage-4 review — all eight fixed

Codex became usable again at the end of the program and reviewed the whole diff against
`cfb2d74`. It raised one P1 and seven P2s. Every one was legitimate; none was disputed.

### P1 — `/control/` login ignored the password switch *(fixed)*

`password_enabled=False` was enforced in `LoginView`, which is the JWT API. `/control/login/`
is Django's own `AdminSite` login and never consulted it, so a superadmin could still sign in
with a password on the exact surface that can turn the switch back on — which made the whole
policy advisory. `AdminSuperuserOnlyMiddleware` now refuses that POST **before the form
authenticates**, so no session is minted. Existing sessions are untouched, matching A2.

### The seven P2s *(all fixed)*

| Finding | Why it mattered | Fix |
|---|---|---|
| Restricted/suspended members were registrable for events | The console became the way around an access restriction | `user__access_status=ACTIVE` on both the registration lookup and the picker |
| A malformed `project_id` cleared the **avatar** | `?project_id=abc` fell through to the avatar branch and destroyed a different image | Present-but-unparseable is now a 400 |
| Profile image swaps took no row lock | Two overlapping uploads both charge storage and free the same old key; one object is orphaned and the counter stays overcharged | `select_for_update()` reload inside the transaction, matching `services_images._locked_event` |
| Profile mutations emitted no audit entry | Breaks the repo-wide append-only invariant | `member.profile_updated` / `member.profile_image_*`, with the **content deliberately excluded** — the log is append-only, so copying a bio into it would make member PII permanently undeletable |
| An image refetch wiped unsaved profile edits | A member who wrote a bio then changed their avatar lost the bio silently | The form re-seeds only when not dirty; image URLs still merge through |
| Staff registration could not answer a required custom form | Every console registration for such an event was a permanent 400 | The existing `CustomFormFields` renderer is wired in, with client-side and server-side errors shown per question |
| The GitHub refresh had a command but no schedule | `GITHUB_API_TOKEN` set and the count still permanently `None` | `apps.makerspaces.tasks.refresh_github_contributions_task` + a daily `CELERY_BEAT_SCHEDULE` entry |

Two of these are worth remembering beyond their fix. The audit gap and the image race are both
cases where the new code followed the *shape* of an existing pattern (`services_images`) without
carrying over the parts that were not visible in the shape — the lock and the audit call. And the
custom-form gap is the cost of testing a new path against the events it happens to create: no test
gave an event a required custom form, so the whole class stayed invisible.

---

## Fixed during the build

### M1 — the direct-handout panel crashed on every load *(fixed)*

`GET /admin/makerspace/<id>/direct-loan-members` is a DRF `ListAPIView`, so it answers with the
paginated envelope. The staff console typed it as a bare array and called `.map` on it, which is a
`TypeError` at render time and takes the whole Direct handout panel down with it — the panel through
which every front-desk handout is issued.

Not a security defect, but an availability one on a Hard-Rules path, and the walk-in feature was
about to be built on top of it. Fixed with the same unwrap the containers dropdown beside it already
used, and the request now asks for a large page so the roster is not silently truncated at the
default page size.

### M2 — walk-in creation could have bound an existing account *(fixed before it shipped)*

The first draft of `walk_in_services` reused an existing `User` when the typed email matched one, in
the shape `invite_membership` uses. Under an endpoint gated on `ISSUE_DIRECT_LOAN` that would have
meant anyone able to hand out a tool could attach an arbitrary existing account to their makerspace's
roster by typing its email — and, worse, silently **reactivate a membership somebody deliberately
revoked**, because `_activate_membership` reactivates a non-active row.

Now a known email is refused outright and the caller is pointed at the members list, which is
`MANAGE_MAKERSPACE`. Binding an account to a roster is a membership decision; this form names
strangers. Verified by `test_a_known_email_is_refused_and_never_binds_to_the_account` and
`test_an_email_this_space_already_knows_is_refused_not_reactivated`.

---

## Verified boundaries

| Area | Property | Where |
|---|---|---|
| Walk-in records | Grant no action anywhere, are not staff, are not superuser | `test_a_walk_in_record_grants_no_authority_anywhere` |
| Walk-in records | Cannot be signed into by any input (unusable password) | `test_a_walk_in_record_cannot_be_signed_into` |
| Walk-in records | Confined to the creating makerspace | `test_a_walk_in_is_confined_to_the_makerspace_that_created_it` |
| Walk-in records | Charged against the managed `members` quota | `test_walk_in_creation_is_charged_against_the_member_quota` |
| Identity seam | Staff sign-in never gated by `accounts` | `test_staff_surface_is_never_gated` |
| Identity seam | A configured OIDC provider never gated; a slug cannot fake the namespace | `test_a_configured_oidc_provider_is_never_gated` |
| Identity seam | Phone login refused on **confirm** as well as start | `test_member_login_surfaces_close_and_config_says_so` |
| Login switches | Password + social both off is refused (console would be unreachable) | `test_password_and_social_can_never_both_be_off` |
| Login switches | Disabling social is refused when it is somebody's only credential | `test_disabling_social_is_refused_when_it_is_somebodys_only_credential` |
| Login switches | No row is written by an unauthenticated login attempt | `test_the_switch_row_is_never_written_by_an_anonymous_request` |
| Profiles | An image key from another makerspace is refused | `test_a_profile_image_key_from_another_makerspace_is_refused` |
| Profiles | A member cannot edit another member's project | `test_a_member_cannot_edit_another_members_project` |
| Profiles | Publishing never publishes email or phone | `test_publishing_a_profile_never_publishes_contact_details` |
| Profiles | A member of another space cannot read the directory or a detail | `test_a_member_of_another_space_cannot_read_this_directory` |
| Profiles | A revoked member leaves the directory and their detail 404s | `test_a_revoked_member_disappears_from_the_directory` |
| Profiles | A restricted account cannot reach its own profile | `test_a_suspended_account_cannot_reach_its_own_profile` |
| Profiles | `javascript:`, `data:`, `vbscript:`, `file:` links all refused | `test_profile_links_reject_every_scheme_but_http` |
| Profiles | Uninstalling `membership` closes the surfaces and keeps the rows | `test_uninstalling_membership_closes_the_profile_surfaces_but_keeps_the_data` |
| Event registration | A member of another makerspace cannot be registered | `test_a_member_of_another_makerspace_is_refused` |
| Event registration | Capacity, duplicates and the module gate all still apply | `tests/events/test_staff_registration_p13.py` |
| Modules console | Superadmin-only (`IsActiveSuperAdmin` on all three views) | `apps/admin_api/views_modules.py` |
| Razorpay | HMAC-SHA256 over the raw body, compared with `compare_digest` | `apps/payments/providers/razorpay.py` |

Two points worth calling out from that table because they are easy to get wrong:

- **Link schemes.** Project links render as an `href` on a page other members read, so an allowlist
  is the entire defence — escaping the link *text* does nothing for the destination. `data:` and
  `vbscript:` are tested alongside `javascript:` because an allowlist written as a `javascript:`
  denylist is the classic version of this bug.
- **The phone-login confirm check.** Gating only the start endpoint would leave a code issued a
  minute before the switch still able to mint a session afterwards.

---

## Accepted risks

### A1 — a walk-in form discloses whether an email already has an account

Refusing on a known email tells the caller that email exists somewhere on the platform. The caller
is authenticated staff holding `ISSUE_DIRECT_LOAN` in a real makerspace, so this is not an
unauthenticated oracle; on managed hosting it is nonetheless a small cross-tenant signal.

Accepted, because the alternative is worse in both directions: succeeding would bind an existing
account (finding M2), and silently dropping the typed email would store a record the staffer
believes carries contact details and does not. The same signal is already obtainable through
`attach_staff_membership`'s break-glass path.

### A2 — a login-method switch does not revoke live sessions

Switching password sign-in off refuses new sign-ins immediately; an access token already issued keeps
working until it expires, and its refresh cookie keeps rotating. Verified deliberately by
`test_disabling_passwords_does_not_revoke_a_live_session`.

Accepted as correct: a login-method switch is a policy change about *how people may sign in*, not a
revocation. Revoking access is what suspend/restrict and membership revocation are for, and
conflating them would make an administrative preference change log everyone out mid-task. Anyone who
needs the stronger effect should suspend the accounts.

### A3 — forgot-password still works while password sign-in is off

`/auth/forgot-password` is not gated by the password switch, so a reset email can still be sent for a
credential that currently cannot be used. Accepted: the flow is enumeration-safe and harmless, and
gating it would strand anyone caught mid-reset when the switch flipped. The staff login screen already
hides the link when the switch is off, so it is not reachable by accident.

### A4 — the accounts-off web flow currently has no OIDC button

The design says an accounts-off deployment authenticates members through its own OIDC provider. The
backend supports that today, but it accepts an **ID token** and no frontend renders configured
providers — so on the web, accounts-off in practice means staff-created walk-in records only.

This is a functional gap rather than a vulnerability, and it is stated plainly rather than papered
over. Closing it means a real browser OIDC flow (authorization-code with PKCE, redirect handling,
discovery), which is its own phase. **Recommended as the next piece of work.**

---

## Pre-existing, not introduced here

### P1 — `BookableSpace` images and the storage reconciler

Already fixed in this program (`bab1e41`) — noted only because CLAUDE.md still described it as an
open gap and now does not.

### P2 — an event registration requires a contact number

`EventRegistration.phone` is non-blank, so a member whose account carries no number could not register
at all, publicly or otherwise. Staff registration now accepts a fallback number, which turns a dead
end at the desk into a question the staffer can ask; the public path is unchanged and a member with no
number on file still cannot self-register. Worth revisiting as a product decision — the constraint
itself was never reviewed.

---

## Residual notes

- **`profile_for()` creates a row on a GET of the caller's own profile.** A write on a read path,
  idempotent and confined to the caller's own row. Left as is because every later write then has a row
  to lock and a stable id for images to hang off; flagged so it is not mistaken for an oversight.
- **`member_identity` and the module gates fail OPEN**; the access rules fail closed. That difference
  is deliberate and is now written into CLAUDE.md — a broken capability lookup must never be the reason
  nobody can sign in, and it must never be the reason a makerspace's alerts go silent.
- **The registry drift guard was blind to 18 files** until a UTF-8 BOM was stripped from each and the
  guard was made to fail hard on an unparseable file (phase 2). Any future "no call site references
  this key" result is now trustworthy; before that change it could have meant "the guard never read the
  file that does".
