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
and is fixed here** (M0). Two further medium items were found and fixed during the build. Nine
Codex Stage-4 passes then found **thirty more defects between them — eight, six, three, two, two,
two, two, three, two** — all fixed. Five risks are accepted with reasons, and only A5 is expected to
be retired. A6 was accepted in round 6 and retired in round 8 after the assertion supporting it was
proved false. Two risks are pre-existing and untouched by this program, and one further pre-existing
platform property is mitigated rather than eliminated (R2-P1, presign orphans).

**The single most useful conclusion here is procedural, and it got stronger with each round:**

- Round 1 reviewed the program and found eight defects.
- Round 2 reviewed round 1's fixes and found six more, including a **permanent lockout created by
  round 1's own fix**.
- Round 3 reviewed round 2's fixes and found three more, including a **round-1 fix that had never
  worked at all** — a console prompt matching on an error message that could never contain the word
  it looked for.
- Round 4 reviewed round 3's fixes and found two more, including a fix that **broke an invariant
  written into `CLAUDE.md` in the same session**.
- Round 5 reviewed round 4's fixes and found two more, including a **fourth distinct way into the
  same walk-in credential boundary**.
- Round 6 reviewed round 5's fixes and found two more, including a **fifth credential writer on that
  same boundary**; the other finding became accepted risk A6 on the false assertion that no durable
  signal distinguished walk-ins after a tenant purge.
- Round 7 reviewed round 6's fixes and the surrounding substrate and found two more: **every DRF
  throttle was only per worker**, and the beat-less scheduler held a database row lock across a
  potentially minutes-long GitHub refresh.
- Round 8 reviewed round 7's fixes and the report's own settled reasoning and found three more:
  **A6 had dismissed a durable signal already present on the global user row**, quota accounting
  trusted a best-effort delete that hid failure, and a post-consumption guard emitted no audit entry.
- Round 9 reviewed round 7's shared-cache fix and scheduler regression test and found two more:
  **the cache fallback broke the multi-worker cloud profile cited to justify it**, and the scheduler
  test could pass while the task still ran inside the transaction it claimed to exclude.
- The test suite, separately, caught a regression no review saw: round 1's beat entry with no
  beat-less counterpart.

**The counts (8, 6, 3, 2, 2, 2, 2, 3, 2) are weaker evidence than they look.** Rounds 4 and 5 each
found a P1, and both were on the walk-in credential seam rather than anywhere new — so the trend
mostly reflects one intricate area being peeled a layer at a time, not the work approaching clean.
Treat a falling count as a reason to keep going, never as a reason to stop.

*No pass came back clean the first time, and every pass found defects in the previous pass's fixes.*
A review that returns nothing is one sample, not a verdict — and a fix is a change, so it needs the
same scrutiny as the code it replaces. That is the standing rule this document exists to record.

Two structural lessons, both earned the expensive way:

1. **Writing an invariant down does not enforce it.** R4-P2 broke a rule its author had documented
   hours earlier, in a file that demonstrated the correct pattern two functions below. Guards and
   reviewers enforce; prose reminds.
2. **A fix that names its own exception must implement the whole exception.** R4-P1 was not a missed
   case — round 3 explicitly identified the upgrade path as the one state its reasoning did not
   cover, then covered a quarter of it. Scoping an exception correctly and then under-building it
   reads, in review, exactly like not having thought about it.

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

## Found by the Codex Stage-4 review, round 1 — all eight fixed

Codex became usable again at the end of the program and reviewed the whole diff against
`cfb2d74`. It raised one P1 and seven P2s. Every one was legitimate; none was disputed.

### P1 — `/control/` login ignored the password switch *(fixed, then corrected in round 2)*

`password_enabled=False` was enforced in `LoginView`, which is the JWT API. `/control/login/`
is Django's own `AdminSite` login and never consulted it, so a superadmin could still sign in
with a password on the exact surface that can turn the switch back on — which made the whole
policy advisory. `AdminSuperuserOnlyMiddleware` now refuses that POST **before the form
authenticates**, so no session is minted. Existing sessions are untouched, matching A2.

**This fix was right about the hole and wrong about the consequence.** Round 2 found that it
created a permanent lockout; the enforcement is now conditional. See R2-P1 below and A5.

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

## Found by the Codex Stage-4 review, round 2 — all six fixed

The same command re-run over the round-1 fixes. **It found six new defects in code round 1 had
already read, including two P1s and a lockout created by round 1's own fix.** That is the finding
that matters most in this document: a review pass returning nothing is one sample, not evidence.
Every review here has been re-run until it came back clean, and none of them came back clean the
first time.

### R2-P1 — a walk-in could be turned into a real account by forgot-password *(fixed)*

A walk-in is created with an **unusable password**, which is what makes it a person record rather
than a login. That is not a boundary: `ForgotPasswordView` finds any active user by email and
`ResetPasswordConfirmView` calls `set_password`, which *replaces* an unusable password perfectly
happily. Staff type an email address at the counter so they can reach someone about a loan —
whoever holds that mailbox could then request a reset and sign in, walking straight past disabled
self-registration into a membership somebody else created for them.

Fixed with a durable `User.is_walk_in` marker (migration `accounts/0014`) checked on **both** reset
paths — the request side and the confirm side, so a link minted before the record was marked still
fails. The generic acknowledgement is unchanged, because refusing visibly would disclose which
addresses belong to walk-ins.

The lesson generalises past this bug: **an unusable password is a statement about the present, not
a constraint on the future.** Every path that can *set* a password has to know the record is not
supposed to have one.

### R2-P1 — the round-1 `/control/` fix was a permanent lockout *(fixed)*

Round 1 closed the password door on `/control/`. The question it did not ask was what was left.
Social sign-in mints **JWTs for the React console and never a Django session**, so with
`password_enabled=False` there was no route into `/control/` at all — and `/control/` is the only
surface that can set the switch back. The deployment sealed itself the moment the last admin
session expired, with no application-level recovery.

Enforcement is now conditional on `settings.PLATFORM_ADMIN_SSO` — a declared flag, default False,
meaning "this deployment has a password-free way into `/control/`". Until such a route exists the
control plane keeps its password door and the switch governs the application surfaces, which is
what it is actually for. The consequence is documented rather than hidden: see A5.

**A fix to an auth path needs its own "what is now unreachable?" check**, not just "is the hole
closed?". Both halves are the review; round 1 did one of them.

### R2-P1 — member image presign strands objects nothing can name *(mitigated, not eliminated)*

`presigned_upload` hands out write access to an object key **before any row claims it**, and
nothing forces the caller back to attach. In POST mode — the default, and what MinIO uses — the
presign targets the **final** key, so an unattached upload lands directly in the served
`member/<makerspace_id>/…` namespace. It is then invisible three ways at once, because all three
mechanisms walk rows: `limits.add_storage` is charged at attach, `recompute_storage` sums rows, and
every purge collector enumerates rows. The object outlives everything that could name it.

This is a **pre-existing property of every public-image presign on the platform**. What is new is
that this one is reachable by an ordinary member rather than behind a staff action.

Mitigated with `MemberImagePresignThrottle` — a per-**member** cap (20/hour, `THROTTLE_MEMBER_IMAGE_PRESIGN`)
keyed on the account rather than the address, and applied to POST only so that a member who spends
their uploads does not lose the ability to *clear* an image, which is the one action that frees
storage. That bounds how much one member can strand; it does not make orphans impossible.

**Eliminating them needs one of two platform-wide changes, and both are their own phase:** presign
into the `staging/` prefix in POST mode as well (so an unclaimed object never enters the served
namespace and a bucket lifecycle rule can expire it), or a sweeper for unclaimed keys. Either
touches every image path in the system, which is why neither was done under a review fix.

### The three P2s *(all fixed)*

| Finding | Why it mattered | Fix |
|---|---|---|
| An email-less walk-in could not be registered for an event | `EventRegistration.email` is non-blank, so the members this program *made* registrable were exactly the ones that could not be registered — the phone fallback had already been added for the identical reason and the email case was missed | `member.email or email` in `register()`, an optional `email` on the staff serializer, **and the matching console field** — the backend fallback is unreachable without it, which is the same as not having it |
| The `membership` purge deleted profile images without freeing the quota | A managed makerspace's `storage_bytes_used` stays permanently inflated, blocking uploads for storage nothing holds, until an operator happens to run the reconciler | `_free_member_image_storage` runs before the delete, skipping objects already gone (`object_size` returning `None` must not be charged back) |
| The GitHub refresh could write one account's count under another's handle | A member changes their handle while the HTTP call is in flight; the unconditional `.update()` writes the old account's total onto the new name. That is a false claim about a person, not stale data | The `.update()` is filtered on the handle that was actually **fetched**, so a raced write is dropped rather than applied |

### Found by the suite, not by either review: the GitHub refresh never ran in cloud mode

Round 1's own fix for "the GitHub refresh had a command but no schedule" added the task to
`CELERY_BEAT_SCHEDULE` and not to `run_scheduled_tasks.SCHEDULED_TASKS`, so on a **beat-less
deployment** — the cloud profile — the count stayed permanently `None`, which is the exact
symptom that fix existed to remove. Caught by the drift guard written for precisely this
(`test_every_beat_entry_has_a_beat_less_counterpart`) and fixed by adding the counterpart entry.

Worth noting alongside the two review passes: **the existing drift guard caught what two rounds of
review did not.** A guard that fails on a category of mistake outperforms re-reading the diff.

---

## Found by the Codex Stage-4 review, round 3 — all three fixed

Round 3 reviewed round 2's fixes and found **three more, two of them P1** — including one showing a
round-1 fix had never worked at all. Same pattern a third time.

### R3-P1 — staff password reset walked straight past `is_walk_in` *(fixed)*

The round-2 fix closed forgot-password. It did not close `reset_user_password`, which is the staff
recovery path: a space manager picks a member, and the service **hands back a usable temporary
password**. Applied to a walk-in that is a one-click conversion of a person record into a login —
strictly easier than the mailbox route the flag was added to close, and available to any manager in
the makerspace.

Refused in the **shared service**, because both the REST endpoint and the Django admin action call
it and a check in either one alone leaves the other open. The refusal is narrow: an ordinary
member's reset is untouched, pinned by its own test.

The lesson is the round-2 lesson not fully learned: closing *a* path that creates a credential is
not the same as closing *every* path that creates one. The right question was "what else calls
`set_password`?", and it was asked one round late.

### R3-P1 — the backfill marked the row and left the credential working *(fixed)*

On an upgrading database, a walk-in that had already been through the vulnerable forgot-password
flow holds a **real password**. Migration `0015` set `is_walk_in=True` and stopped there — and the
login and refresh paths deliberately do not consult the flag, so the accounts the migration exists
for could still sign in afterwards. A marker that changes nothing about the state it describes is
not a fix.

The backfill now also writes the unusable-password sentinel and blacklists outstanding refresh
tokens (best-effort, guarded on `token_blacklist` being installed). The reverse deliberately does
**not** restore those credentials: they were usable only because of the hole, and handing them back
would reopen it.

**Why enforcement stays at credential *creation* and not at login:** after these fixes there is no
application path by which a walk-in can come to hold a password, so a login-time check would guard
a state that cannot occur — while blocking a superadmin who deliberately set one in `/control/`,
which the repo's standing rule says always overrides. The one case where the state *could* already
exist is the upgrade, and that is exactly what the backfill handles.

### R3-P2 — the contact prompts had never once appeared *(fixed)*

`StructuredApiError` builds its `message` from `Object.values(body)` alone, so a DRF field error
arrives as the bare string `"This field cannot be blank."` — containing neither `"phone"` nor
`"email"`. The console matched on that message, so the prompt never rendered.

**This means round 1's phone fallback was dead from the day it shipped**, and the round-2 email
fallback was a faithful copy of a broken pattern. Both now read the field-keyed
`StructuredApiError.body`. A console field that cannot be triggered is indistinguishable from an
absent one, which is the same failure as a backend fallback with no console field — the two halves
of the same mistake, one round apart.

---

## Found by the Codex Stage-4 review, round 4 — both fixed *(fixes written by Codex)*

From this round on, **Codex applies the fixes** and Claude verifies them, per owner direction. Both
findings were in code Claude had written in round 3.

### R4-P1 — the backfill revoked the password and left everything it had unlocked *(fixed)*

A walk-in who went through the old hole had a **working session**, and a session is not a password —
it is the means to attach credentials that outlive one. Three of them, each with a login path that
never reaches the `is_walk_in` guard:

- **`SocialIdentity`** — `resolve_social_identity` returns as soon as an existing identity matches
  the provider subject, **before** the round-3 auto-link guard. A linked Google account signs them
  straight in.
- **`phone_e164` + `phone_verified_at`** — a verified number is a login identity in its own right,
  resolved *by number*, and phone login never reads the marker.
- **`DeviceGrant`** — a native grant mints its own rotating refresh family, so blacklisting the
  current tokens does nothing about the next one.

The backfill now clears all three alongside the password. This is round 3's own reasoning failing on
its own terms: it argued enforcement belongs at credential *creation* and named the upgrade as the
single exception the backfill handles — then handled one credential type in that exception. **The
argument was right and the exception was implemented at a quarter of its stated scope.**

Still deliberately *not* a login-time check: after these fixes no application path can give a
walk-in any of the three, so a permanent guard on every login path would be paying forever for a
window that has closed.

### R4-P2 — the storage fix violated an invariant written down in this repo *(fixed)*

Round 2's `_free_member_image_storage` ran inside `purge_module`'s `transaction.atomic()`, holding
the makerspace `select_for_update` lock, doing one network HEAD per image. A `StorageUnavailable`
would have **rolled back the entire row purge**, and the lock was held across N round trips —
against an explicit rule in `CLAUDE.md` that per-module storage cleanup happens *after commit* and
*best-effort*, in a file whose own `_delete_private_keys`/`_delete_public_image_keys` already
demonstrate the pattern immediately below.

Now `module_purge._free_public_image_storage`, called post-commit next to the object deletion,
best-effort, and **generic over `public_keys`** rather than membership-specific — every module purge
that deletes image-holding rows had the same gap, so fixing it only for `membership` would have left
the others to be found later.

Worth stating plainly: this was a rule the author had written into `CLAUDE.md` **in the same
session** and then broke. Documentation of an invariant does not enforce it; only a guard or a
reviewer does.

---

## Found by the Codex Stage-4 review, round 5 — both fixed *(fixes written by Codex)*

### R5-P1 — an access token could rebuild what the migration revoked *(fixed)*

Migration `0015` blacklists **refresh** tokens. A browser **access** token stays valid for up to
fifteen minutes after it runs — and `resolve_social_identity` returns through `_explicit_link`
*before* the round-3 `is_walk_in` guard. So inside that window a walk-in could call the explicit-link
endpoint, attach a **new** provider identity, and regain permanent access: the migration deletes the
old identities, and this mints a replacement.

The guard now lives **inside `_explicit_link`**, after its `select_for_update` so it reads a fresh
row, raising `walk_in_record` / 403. Placing it there rather than at the calling branch is the point
— every explicit link in the system is created through that one function.

This is the third consecutive round to find a hole on this seam, and the shape has been identical
each time: **the guard went on the path being looked at rather than on the function every path
converges through.** Auto-link (round 3), the staff reset service (round 3), the durable identities
(round 4), and now explicit linking. The correct instinct throughout would have been to enumerate
every writer of a credential *first* and guard the chokepoint, rather than closing doors one at a
time as a reviewer pointed at them.

### R5-P2 — a fallback contact carried across members *(fixed)*

Select walk-in A, receive the missing-email prompt, type A's address, switch the picker to walk-in B,
submit — B is registered with A's email. The state was cleared only on a *successful* mutation, and
changing the selection is not success. The backend cannot catch this: B genuinely has no account
email, so the fallback is exactly what it is supposed to accept.

Consequence is a silent misdelivery — B's event mail goes to A, with nothing in either interface to
show it. Now reset on picker change. Custom-form answers deliberately survive the change: those
belong to the event, not the person.

Covered by `frontend/src/features/staff/EventRegisterMember.test.tsx`, which also pins the
field-keyed error reading from R3-P2 — the first frontend test this component has had, which is
itself part of why two bugs lived in it across three rounds.

---

## Found by the Codex Stage-4 review, round 6 — one fixed, one accepted

### R6-P1 — phone linking was the fifth way in *(fixed, by Codex)*

`confirm_link` writes a verified `phone_e164`, and **a verified number is itself a login identity**,
resolved by number rather than by account. It never consulted `is_walk_in`, so a walk-in holding a
live access token could rebuild OTP login after migration `0015` had revoked everything else.

Guarded inside `confirm_link`'s `transaction.atomic()`, on a row re-read under `select_for_update`
(the caller's `user` came off a JWT and may be stale), using the file's **deferred-raise** pattern —
raising inside the block would roll back the `failed_attempts` increment and silently disable the
attempt cap, which that function's own comment warns about. `start_link` is refused too, since it
writes a challenge row and spends real SMS credit.

**This is the sixth occurrence of one mistake, and the fifth round to find it.** The previous round
had already written the correct rule into `CLAUDE.md` — *enumerate every writer of a credential and
guard the chokepoint* — and the next commit still guarded a path rather than enumerating. Writing a
lesson down is not the same as applying it; the enumeration should have been done once, as a list,
the first time the pattern appeared. The full set is now: forgot-password, reset-password confirm,
the staff reset service, social auto-link, social explicit link, and phone link (start + confirm).

**The enumeration was then finally done properly, and it came back clean.** Grepping every
`set_password`/`set_unusable_password`, every `phone_e164`/`phone_verified_at` write and every
`SocialIdentity` create found four more writers, all safe by construction: change-password requires
`check_password` (an unusable password always fails), sign-up only enters its `set_password` branch
when the row does not exist, phone unlink only clears, and the CLI commands sit behind shell access.
One residual worth naming rather than fixing: a stranger who knows a walk-in's address can trigger
the verification email and get `email_verified_at` stamped on that record. It grants nothing —
every login path checks the marker, and auto-link checks `is_walk_in` explicitly rather than
inferring safety from `email_verified_at`, which is precisely why round 3's guard was written that
way instead of relying on the coincidence. Both the guarded and the audited-safe lists are now in
`CLAUDE.md`, so the next person does not repeat the search or add redundant guards.

**Five minutes of grep would have replaced five review rounds.** That is the whole lesson.

### R6-P2 — walk-ins from a purged makerspace are unmarked *(accepted, A6)*

The backfill identifies walk-ins from `member.walk_in_created` audit rows. Those are
**makerspace-scoped**, so `lifecycle.purge()` deletes them along with the memberships — while the
global `User` rows survive, because `User` is platform-level. A walk-in whose makerspace was purged
before the upgrade therefore keeps `is_walk_in=False` and stays eligible for forgot-password.

**Accepted rather than fixed, because every available alternative is worse.** No other durable
signal identifies these rows: `source="walk_in"` is passed to `_activate_membership` for the welcome
email and never persisted, and matching on "unusable password" would also match invited accounts
that have not set one yet — marking those would lock real people out of their own recovery, which is
a live harm traded for a historical one. The residual is genuinely narrow: such a user has **no
membership anywhere**, so converting the account grants access to nothing beyond the public
catalogue, and it requires a makerspace purge (superadmin-only, irreversible, rare) to have happened
before the upgrade.

The right long-term fix is a persisted `source` on the membership or a platform-scoped audit event
at walk-in creation — either would survive a tenant purge. Both are schema changes and belong to
their own phase, not to a review fix.

---

## Found by the Codex Stage-4 review, round 7 — both fixed

### R7-P1 — the rate limits were never global *(fixed)*

Django had no `CACHES` setting at all, so it silently used a per-process `LocMemCache`. Production
runs three Gunicorn workers, which meant **every DRF throttle on the platform** — login, phone OTP,
password reset, and the new member-image-presign cap — allowed three times its configured rate and
forgot its counters whenever a worker recycled. An attacker did not need to know which worker they
hit; ordinary load balancing distributed attempts across all three.

This is a **pre-existing platform-wide weakness that the new presign throttle inherited and made
visible**, not a defect specific to maker profiles. The cap added in round 2 had been accepted as a
mitigation without checking where its counter lived, so its advertised rate was never the rate the
production topology enforced.

Fixed by configuring `CACHES` with Django's built-in `RedisCache` whenever `CACHE_URL` or an
explicitly set `CELERY_BROKER_URL` is present. The original fallback to `LocMemCache` was incorrect;
round 9 replaced it with Django's `DatabaseCache`. See R9-P1.

The general lesson is that **a mitigation is only as strong as the substrate it is stored in**.
“Add a throttle” was treated as complete without asking where the counter lived; the configured
number meant something different in development and production.

### R7-P2 — the beat-less scheduler held a row lock across network I/O *(fixed)*

The GitHub refresh added in an earlier round makes one HTTP request per profile with a ten-second
timeout. `run_scheduled_tasks` called the runner **inside `transaction.atomic()`**, while holding
`select_for_update()` on its `PeriodicTaskRun` row. A sufficiently large or slow batch could
therefore freeze member-profile edits for minutes, and if the runner exited the entire transaction
rolled back as though the scheduler had never claimed the work.

Restructured to **claim, then work**: a short transaction takes the row lock, checks due-ness and
stamps `last_run_at`, then commits; the task itself runs outside the transaction. That makes the
beat-less scheduler at-most-once if a process dies after the claim. The trade is deliberate and
matches this file's existing conclusion for return reminders: sending one twice is worse than
sending it late.

The general lesson is more uncomfortable than the fix: this was the **third time in one session**
that external I/O was placed inside a transaction holding a lock; the membership-purge storage HEAD
in round 4 was the same mistake. Being told once did not generalise. The rule has therefore been
written at the architectural level: HTTP and object-storage calls do not sit inside a locked
transaction.

### Guards added beyond the findings

At the owner's request, explicit `is_walk_in` refusals were added to three paths the round-6 audit
had assessed as safe by construction:

- **Change-password** was unreachable because `check_password` always fails against an unusable
  password. It now refuses a walk-in explicitly, so the reason is stated at the boundary rather
  than depending on that indirect property.
- **Member sign-up** reused an existing row by email and never set a password on it, but it did let
  an unauthenticated stranger get `email_verified_at` stamped on a walk-in record. It now returns
  silently for a walk-in, because the endpoint must never disclose whether an account exists.
- **`seed_demo` and `setup_instance`** now assert against username collisions. This is data-integrity
  protection rather than access control — shell access already overrides the application — but it
  prevents the commands from reusing a walk-in identity accidentally.

Phone **unlink** was deliberately not guarded. It only clears a credential; guarding a revocation
path would make a walk-in's phone identity unremovable, which is the opposite of the boundary's goal.

---

## Found by the Codex Stage-4 review, round 8 — all three fixed

### R8-P1 — the walk-in backfill missed users whose makerspace had been purged *(fixed)*

This is the most important entry in the eighth round because **round 6 raised this exact finding and
this report accepted it as A6**. The acceptance rested on a categorical assertion: “no other durable
signal identifies these rows.” That assertion was false.
`makerspaces/walk_in_services._available_username()` generates every walk-in username as
`walkin_<name>_<random>`, and the username lives on the global `User` row, so a tenant purge does not
touch it. Self-registration uses the separate `member_<uuid>` namespace, so the two cannot collide.

This was an error of judgment, not a tradeoff that later changed. A five-second look at the username
generator would have falsified the premise, and the author had already read and quoted that function
elsewhere in the same session. The unsupported assertion was then written into this report as settled
reasoning. The reviewer had to re-raise a finding the report had explicitly dismissed. **That is
exactly why a review loop must not treat a documented dismissal as closed**: accepted risk is still a
claim about the code, and prose does not make the claim true.

The backfill now uses the **union** of the audit-derived lookup and the `walkin_` username prefix, and
applies every revocation to both sets. A6 is retired below rather than erased; preserving the bad
decision and its correction is the point of this report.

### R8-P2 — storage quota could permanently undercount *(fixed)*

`module_purge` freed quota **before** deleting the object. That ordering correctly preserved the size
returned by HEAD, but it ignored the failure semantics of the next call:
`public_image_storage.delete_object` swallowed its own `BotoCoreError`/`ClientError`. A failed delete
therefore looked like success to the purge path — the counter dropped while the object survived,
permanently undercounting in the direction that grants the makerspace free storage.

`delete_object` now returns `True` or `False`, and one merged loop HEADs the size, deletes the object,
and frees the quota only on confirmed deletion success. This corrects the instruction the author gave
in round 4 — “free before deleting, or the HEAD finds nothing.” It was right about the ordering
constraint and wrong about the failure case. **Knowing why one order is necessary is not enough; the
state change still has to be conditional on the operation that justifies it succeeding.**

### R8-P3 — a refused walk-in phone link was unaudited *(fixed)*

By the time the round-6 walk-in guard runs, `_confirm` has already persisted `consumed_at` on the
challenge. Refusing the identity link did not undo that consumption — nor should it — but the branch
emitted no audit event. A state change had therefore happened without a record, against this repo's
rule that every state-changing path emits an audit entry.

The refusal branch now records `member.phone_link_refused_walk_in`. The general shape matters more
than this one event: **A GUARD IS ITSELF A STATE-CHANGING PATH when it runs after something has already
been consumed.** A guard is not automatically read-only merely because its final result is refusal.

---

## Found by the Codex Stage-4 review, round 9 — both fixed

### R9-P1 — the shared-cache fix did not cover the profile it named *(fixed)*

Round 7 configured a shared cache so DRF throttles would stop being per-process, then kept a
`LocMemCache` fallback on the stated grounds that “the cloud profile is a single process with no
Redis.” **That claim is false.** `docker-compose.cloud.yml` sets `CELERY_BROKER_URL` to empty and runs
Gunicorn with `--workers ${GUNICORN_WORKERS:-3}` and `--max-requests 1000`. The one profile named as
the reason for the fallback was therefore the profile it broke: three independent local-memory
caches made every throttle effective at three times its configured rate — login, phone OTP,
password reset, and the member-image-presign cap — and each worker recycle reset that worker's
counters again.

The fallback is now Django's `DatabaseCache`, which is shared by all Gunicorn workers. A new
operations migration creates the cache table, so the correction requires no separate operator step.

This is the **second instance in two rounds of the same failure mode**. The first was A6 in round 8:
a factual claim about the codebase was asserted without opening the file, then written into both a
code comment and `CLAUDE.md` as settled reasoning. The danger is not merely being wrong. It is that a
confident false premise gets documented and then protects itself from re-examination.

### R9-P2 — the regression test could not fail for the reason it existed *(fixed)*

The scheduler lock-boundary regression test asserted against `inspect.getsource` with string
matching. Code that assigned `last_run_at` before the task call but still ran that call inside the
same `atomic()` block satisfied every assertion, while harmless refactoring could break the test.
It checked the source's shape without observing the transaction boundary whose behaviour it claimed
to protect.

Replaced with a behavioural test that runs the management command with the task stubbed to record
`django.db.transaction.get_connection().in_atomic_block`. It uses
`pytest.mark.django_db(transaction=True)` so pytest's own transaction wrapper does not make the
assertion vacuous. The replacement was **VERIFIED** by injecting the real regression — wrapping the
task call in `transaction.atomic()` — and confirming that the test fails with
`assert [True] == [False]`. A test claimed to prove a property should itself be shown to fail when
that property is violated.

---

## Parallel review sweep — five agents, distinct lenses

After nine sequential rounds, each scoped to the diff, five Codex reviewers were run in parallel
with deliberately distinct assignments: the credential/identity boundary, multi-tenancy and RBAC,
concurrency and locking, upgrade and deployment safety, and data integrity and storage. Each was
asked for P1s only, and only with a concrete exploit or failure path. The headline result is plain:
**the parallel sweep found categories nine sequential rounds never examined, because every
sequential round inherited the same diff-shaped blind spot.**

### Four confirmed and fixed — all in code written during this review loop

1. **The walk-in backfill had a latent clean-install failure.**
   `apps/accounts/migrations/0015_backfill_is_walk_in.py` declared a dependency on
   `makerspaces/0001` while using `MakerspaceMembership`, which is created in `makerspaces/0002`.
   Existing runs passed only because Django happened to order the wider migration graph correctly;
   the dependency itself did not guarantee the table the migration queried. It now depends on the
   migration that actually creates that model.
2. **The walk-in username fallback could destroy a hand-created account's credentials.** The
   migration matched `username__startswith="walkin_"`, so any ordinary account an operator had
   created with that prefix was swept into an irreversible credential revocation. It now matches
   the full generated username shape with a regex. The irony is worth preserving: the migration
   docstring rejects “unusable password” as too blunt a heuristic, then shipped a blunter one.
3. **One concurrent logout could roll back every migration revocation.** Between the blacklist
   snapshot and `bulk_create`, a live logout could insert the same blacklist row. The resulting
   uniqueness violation occurred inside the `RunPython` transaction and therefore rolled back
   **every** password, social identity, phone identity, device grant and token revocation performed
   by the migration. The bulk insert now uses `ignore_conflicts=True`.
4. **Two password-reset paths could race the migration and restore a credential after it committed.**
   `ResetPasswordConfirmView` and the staff `reset_user_password` service both did check-then-write
   without locking the user row. A request already in flight could pass the old `is_walk_in` check,
   wait while the migration committed, then install a usable password afterwards. Both paths now
   re-read the user under `select_for_update()` and re-check before writing.

### Three rejected

- **Module purge scoping.** Rejected because `purge_module` has **NO HTTP route**; it is CLI-only,
  and this repo's documented boundary is that `manage.py` access overrides application-layer
  scoping. Anyone who can run it can run `psql`, so adding makerspace RBAC inside the command would
  not create a security boundary.
- **Storage ordering.** Two agents contradicted each other: one wanted quota freed before delete,
  while round 8 established free-only-after-confirmed-delete. Either order loses something on a
  crash, but overcounting leaves a makerspace charged for storage it does not hold, while
  undercounting hands out free storage indefinitely. The safer failure was kept. **Parallel
  reviewers disagreeing is a feature, but their output requires adjudication, not application.**
- **`PLATFORM_ADMIN_SSO` / A5.** Unchanged accepted risk, by the owner's decision.

### Pre-existing P1s found outside this diff — ALL EIGHT NOW FIXED

Eight issues in previously committed code, found by the parallel sweep rather than by any of the
nine diff-scoped rounds, because none of them were in the diff. All are now fixed. The summaries
deliberately omit step-by-step exploit instructions.

**Three of the eight turned out to be one defect repeated across nine sites**, which is the reason
the fix is much wider than the finding list. See "The list was written from one site" below.

#### The two switches that did not switch *(fixed)*

- **Social sign-up ignored the self-registration switch**
  (`apps/accounts/views_social.py`, `apps/accounts/services_social_identity.py`).
  `resolve_social_identity` now takes `allow_user_creation`, passed in from
  `self_registration_enabled()`. The gate covers **account creation only** — the
  `explicit_user` branch and the existing-identity branch both return before it, so linking
  and signing in on an already-linked identity keep working, and `OidcSocialLoginView`
  inherits the gate by subclassing. A refused creation is `registration_disabled` / 403.
- **Device login ignored the password switch** (`apps/accounts/views_device.py`).
  `password_login_enabled()` is now checked **before** `authenticate()` runs, so no
  credential lookup happens and no `DeviceGrant` is minted. It reuses the generic
  credential error, so the endpoint discloses no more than it did before. This one mattered
  more than it looks: a `DeviceGrant` carries its own rotating refresh family, so a password
  accepted there outlives the browser session the switch was believed to have closed.

Both are covered in `tests/accounts/test_login_methods_p10.py`, and **both tests were verified
to fail with the fix removed** — the third test, that an existing identity still signs in, was
verified to stay green, which is what shows the gate is on creation rather than on login.

*A switch that does not switch is worse than no switch: an operator believes a door is closed.*

#### Purge and storage *(fixed)*

- **Module-purge key collection raced new attachments** (`apps/makerspaces/module_purge.py`):
  collection now happens inside the transaction, under the makerspace lock. The comment there
  is deliberately honest that this **narrows rather than closes** the window — under READ
  COMMITTED a row another transaction commits between the collection SELECT and the DELETE is
  invisible to the first and visible to the second, and attach paths take the same makerspace
  lock only in managed mode, because `limits.add_storage` returns early on self-host.
- **`post_delete` deleted storage inside the purge transaction** — in
  `apps/procurement/signals.py` **and `apps/warranty/signals.py`**, which has the identical
  receiver and was not in the finding list. Both now defer to `transaction.on_commit`, so a
  rollback can no longer restore rows whose files are already destroyed.
- **Maintenance purge did not release document quota**
  (`apps/makerspaces/module_purge_collectors.py`): `maintenance_delete` now sums `size_bytes`
  and frees it, following `machine_service_delete`'s existing precedent. Freeing inside the
  transaction is correct here, unlike the public-image path: the size comes from a database
  column rather than an S3 HEAD, so it rolls back with the delete and needs no network call.
  Procurement receipts were checked and are **never charged**, so that collector was left alone.

#### Public images — one defect, nine sites *(fixed)*

The finding list named `apps/makerspaces/profile_images.py`. The same three defects were present
in `events/services_images.py`, `bookings/services_images.py`, `machines/services.py`,
`admin_api/views_inventory.py`, `admin_api/views_makerspaces.py`, `admin_api/views_machine_image.py`,
`inventory/admin_image_uploads.py` and `makerspaces/admin_images.py`.

- **Quota was freed before the delete was confirmed, and the delete often ran inline inside the
  transaction.** `public_image_storage.release_public_image` is now the single implementation:
  HEAD for the size, delete, then free **only** on an affirmative True, all after commit.
  `module_purge._delete_public_images_and_free_storage` was refactored to loop over it rather
  than keep a second copy. The two Django-admin paths use the quota-neutral
  `delete_public_image_on_commit` instead, because they never charge on attach and freeing what
  was never charged is the undercount direction that permanently grants free storage.
- **`apps/bookings/storage.delete_object` returned `None` on success *and* failure**, so
  "free only after a confirmed delete" was unanswerable there — strict checking would never
  free, loose checking would always free. It now returns True/False like the shared one. This
  was not in the finding list and was only exposed by the fix.
- **S3 HEAD calls ran under held row locks.** Every one is hoisted out. In the four view-layer
  sites the HEAD was also redundant: `finalize_upload` already returns the validated size, so
  `result.size` replaced a second round trip outright. That incidentally repaired four of the
  eleven known pre-existing test failures, which were `object_size` 503s on a remapped MinIO port.
- **`public_image_key_in_use` was checked outside the lock that writes the key.** It is now
  re-checked at the write boundary under the holder's row lock, and guarded with a truthiness
  test — an empty key would otherwise match every row that has no image and read as "in use".

**No tenant-wide makerspace lock was added, deliberately.** The first draft of this fix took
`select_for_update()` on the makerspace at every site to serialize claims across holder tables.
That was reverted. Every attach path pins the key to its own `<kind>/<makerspace_id>/` prefix, so
a key can only ever be claimed by a holder of the **same kind**: `items/` only by an
InventoryProduct, `machine/` only by a Machine, `makerspace/` only by that one Makerspace row
(logo and cover both live on it, so its row lock covers both), and bookings keys are narrower
still at `spaces/<makerspace_id>/<space_pk>/images/`. A holder row lock is therefore sufficient.
`member/` is the one kind with two holder tables — an avatar on the profile and an image on each
of its projects — and those are serialized by locking the **profile**, since every member-kind key
belongs to exactly one. A tenant-wide lock would have serialized every image upload in a space
against every other, including on self-host where `add_storage` takes no makerspace lock at all
today.

#### The residual that was accepted, not fixed

The makerspace-vs-holder **lock ordering** is unchanged: an image path takes the holder row lock
and then, in managed mode only, the makerspace lock inside `add_storage`, which is the inverse of
the purge's makerspace-first order. The deadlock is real but its only partner is a superadmin
CLI-only purge, Postgres detects it within `deadlock_timeout` and aborts one side, and both sides
are retryable. The alternatives were both worse: a makerspace-first lock everywhere adds a
permanent tenant-wide serialization point on self-host to prevent a rare self-healing event, and
moving storage accounting post-commit removes the at-attach quota cap for managed hosting. Owner
decision, taken with those three options on the table.

**Also noted and deliberately not fixed:** the two Django-admin image paths do no storage
accounting at all — they never charge on attach and never free on clear. That is internally
consistent, but an image attached through the staff API and later replaced via `/control/` leaves
the original charge stranded until `recompute_storage` runs. Pre-existing, superadmin-only, and
`recompute_storage` is the authoritative reconciler.

### Round 10 — reviewing the fixes above, three more *(all fixed)*

Run against the completed parallel-sweep fixes. It was not clean, which is now the
expectation rather than a surprise: no round in this loop ever has been.

- **R10-P1 — change-password had no locked re-read.** `ChangePasswordView` tested
  `is_walk_in` on `request.user`, built from a JWT that can predate migration `0015`
  marking the record. A request begun while the flag was still false waits on the
  migration's row lock and then writes a fresh **usable** password after the migration
  committed the unusable one — undoing the revocation for exactly the accounts it exists
  for. Now re-reads under `select_for_update()` and repeats the guard next to the write,
  which is what every other credential writer on this seam already did. The complete
  writer list in `CLAUDE.md` was about *which* paths are guarded; this was a different
  axis — whether the guard is **atomic**.
- **R10-P2 — the backfill regex was ASCII-only, and the real blast radius was ordinary
  names.** `_available_username` builds its stem with `char.isalnum()`, true for every
  Unicode letter, but `0015` matched `^walkin_[a-z0-9_]+_[a-z0-9]{6}$`. Verified against
  Postgres rather than reasoned about, which mattered: the review cited Devanagari and CJK,
  but **`José Núñez` → `walkin_josé_núñez_w96uow` also missed**, as did Cyrillic and
  Arabic. Accented Latin names are the common case, not an exotic one. An unmarked walk-in
  whose makerspace was already purged has no audit-derived signal left, so this regex is
  the only thing that can still identify it. Now `[[:alnum:]_]`, which still rejects
  non-walk-in usernames and an uppercase tail. (Devanagari reached the same outcome by
  another route: its combining marks are category `Mn`, not alnum, so they become
  underscores.)
- **R10-P3 — the maintenance quota fix freed bytes before the delete was confirmed, and
  the reasoning written to justify it was wrong.** The comment claimed that taking the size
  from a database column rather than an S3 HEAD made it safe to free inside the transaction.
  That covers a *database* failure only: the rows commit, the best-effort object delete then
  fails in `_delete_private_keys`, and the makerspace stops being charged for storage it
  still holds. `_delete_private_keys` now **returns the keys the bucket confirmed gone**, a
  new `ModulePurgePlan.private_key_sizes` declares the charged bytes per key, and
  `_free_private_storage` releases only the confirmed intersection, after commit.

`machine_service_delete` had the identical free-before-delete shape and was fixed in the
same pass rather than deferred. Its apparent obstacle dissolved on reading the charge path:
`add_storage` fires at **attach** time and writes `size_bytes` in the same save, so
`service_request__isnull=False` *is* the charged set, while the purge deletes every file
row — an unattached upload was never charged and must free nothing. That asymmetry is now
stated in the code instead of being inferred.

### Round 11 — one finding, and it was a rule this report already contains *(fixed)*

- **R11-P1 — the new social refusals consumed a one-time nonce without an audit row.**
  `consume_social_nonce` commits `consumed_at` before `resolve_social_identity` can refuse,
  so the `registration_disabled` gate added in this pass — and the walk-in auto-link and
  explicit-link refusals added in earlier rounds — returned 403 having already mutated
  state, with no trace. `SocialLoginView` now records `auth.social_login_failed` carrying
  the refusal code, and `SocialLinkView` records `auth.social_identity_link_failed`
  against the real actor. The refused address is deliberately **not** logged: the audit
  log is append-only, so an email written there is permanently undeletable PII.

This is the rule already written up as R8-P3 for the phone seam — *a guard that runs after
a challenge or token has been consumed is itself a state-changing path and must emit an
audit entry* — and it was violated again, by me, on the next seam that has one-time state.
Writing a lesson down does not apply it. The check that would have caught it is mechanical:
**when adding a refusal, ask what was already committed before the refusal could fire.**

### The list was written from one site

The finding list named `profile_images.py` for three defects that existed at nine sites, because
that is where the reviewing agent happened to look. Patching only what was named would have left
five to nine siblings holding the identical bug for a later round to rediscover one at a time —
which is precisely what happened across five rounds on the walk-in credential seam, and the lesson
written up there. **A finding names a site; the fix has to name the chokepoint.** Two further
defects (`warranty/signals.py`, `bookings/storage.delete_object`) were found only because the fix
was scoped that way, and neither appeared in any review round.

### Method note

Nine sequential rounds found 30 defects, but all within the diff. One parallel pass with five
assigned lenses found four more in that diff **and eight outside it**. The lesson is that review
scope is inherited from how the review is framed, and repeating the same framing does not broaden
it however many times it is run.

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

### A6 — a walk-in from a purged makerspace is not marked *(retired in round 8)*

A6 was accepted on the false assertion that no durable signal survived a tenant purge. The
`walkin_` username prefix already survives on the global `User` row and does not overlap the
`member_<uuid>` self-registration namespace. The backfill now unions that prefix with the
audit-derived lookup and applies every revocation to both. See R8-P1 for why this was an error of
judgment rather than a tradeoff, and why the overturned acceptance remains on the record.

### A5 — `/control/` keeps a password door while password sign-in is off

Following R2-P1, `password_enabled=False` does **not** refuse a password login at `/control/` unless
`PLATFORM_ADMIN_SSO` says another way in exists. On every deployment today it does not, so a
superadmin can still sign into the control plane with a password after switching passwords off
everywhere else.

Accepted deliberately, and it is the lesser of two evils rather than an oversight. The alternative
is a switch that cannot be un-flipped by any application-level means — recovery would require shell
or database access, which is precisely the position the superadmin-access toggle refuses to put an
operator in (that one requires Platform Email to be configured before it can be turned on, for the
same reason). `/control/` is superadmin-only, rate-limited by django-axes, and deliberately not
proxied on the public frontend port, so it is the platform's break-glass entry rather than a general
surface.

**This is the one accepted risk in this document that is expected to be retired**, by building a
password-free `/control/` route and setting `PLATFORM_ADMIN_SSO`. The enforcement path is already
written and tested (`test_the_control_plane_login_is_refused_once_another_route_exists`) — only the
alternative route is missing.

---

## Pre-existing, not introduced here

### P1 — `BookableSpace` images and the storage reconciler

Already fixed in this program (`bab1e41`) — noted only because CLAUDE.md still described it as an
open gap and now does not.

### P2 — an event registration requires a contact number *and an address*

`EventRegistration.phone` and `.email` are both non-blank, so a member whose account carries neither
could not register at all, publicly or otherwise. Staff registration now accepts a fallback for each,
which turns a dead end at the desk into a question the staffer can ask; the public path is unchanged
and a member with nothing on file still cannot self-register. The account always wins over the
supplied value, so the fallback cannot be used to redirect a member's event mail.

Worth revisiting as a product decision — **the constraint itself was never reviewed**, and it is the
root cause of both this entry and one of the round-2 P2s. Two non-blank contact columns on a model
that now serves walk-in records is a requirement inherited from when every registrant was
self-registered.

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
