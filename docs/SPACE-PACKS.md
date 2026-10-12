# Space packs and saved install profiles

A space pack copies configuration. It is not a backup, tenant dump or restore
artifact and cannot transfer operational history. Enable the **Space packs** feature
(`packs.import`) in makerspace settings to export or import. It defaults off; no
module key was added.

Space Managers use their existing `manage_makerspace` authority in their own space.
Each section also checks the action needed by its normal editor: inventory definitions
need `edit_inventory`, booking rules need `manage_bookings`, and custom role grants
use the existing non-escalation service. Hidden and archived spaces stay excluded.
Only an active superadmin can change the module set or save platform install profiles.
The deployment edition, origins, credentials, limits and superadmin-access policy
cannot be changed by a pack. Self-host module authority is unchanged.

The settings panel exports JSON, previews an import and applies the reviewed content.
Superadmins can save the editor's pack as a named platform profile or load an existing
profile. Makerspace creation accepts a saved install profile; creating the space and
applying its configuration share one transaction. A failure leaves no partial space.
Profiles are create-only snapshots: save a new named profile for a revised version.

## HTTP protocol

All routes are under `/api/v1/admin` and use staff authentication:

| Method | Route | Result |
| --- | --- | --- |
| GET | `/makerspace/{id}/space-pack` | Configuration-only JSON envelope |
| POST | `/makerspace/{id}/space-pack` | Preview by default, or audited atomic apply |
| GET | `/space-pack-profiles` | Superadmin-only paginated profile list |
| POST | `/space-pack-profiles` | Superadmin-only profile creation |
| POST | `/makerspaces` | Optional `install_profile_id` applies a profile at creation |

An envelope has exactly `format`, `version`, `configuration` and `checksum`:

```json
{
  "format": "spaceworks-space-pack",
  "version": 1,
  "configuration": {},
  "checksum": "<64 lowercase hexadecimal characters>"
}
```

The empty configuration above illustrates the envelope only. A real pack must include
every section from the allowlist below. SHA-256 covers the UTF-8 JSON of `format`,
`version` and `configuration`, with sorted object keys, compact separators,
unescaped Unicode and no non-finite numbers. This checksum proves byte integrity,
not authorship or trust. Staff must review imported content. Unknown formats,
versions, fields, modules and features are refused; the maximum is 2 MiB / 2000 entries.
Field values must use the canonical JSON types and spelling produced by export;
coercions such as a string `"false"` in a boolean field are refused so the preview
matches what the domain writers persist. Authored template whitespace is preserved.

Preview body: `{"pack": <envelope>, "dry_run": true}`. The response includes
`applied: false`, `base_checksum` and a `changes` list of section/key/before/after.
Preview performs no writes, audit entries or row creation.

Apply body: `{"pack": <envelope>, "dry_run": false, "base_checksum": "<preview value>"}`.
The target configuration is revalidated under locks. A stale checksum answers 409;
preview again. Missing preview checksum answers 400. Disabled features/modules answer
400. Unauthorized scope answers 404; action/grant refusals answer 403. Every applied
configuration change is audited, with the real User as actor. Any failure rolls back
every step and audit entry in the transaction. Concurrent quota or authority changes
may still cause apply to refuse even after a valid preview.

## Configuration projection

`apps/data_export/space_pack_configuration.py` is the literal allowlist:

- `modules`, `features`: registered capabilities; core modules are required.
- `settings`: existing public inventory/stats, membership aliases, loan/presence,
  staff/booking notification switches. Tenant identity and routing are excluded.
- `opening_hours`: IANA timezone and the validated weekly/exception schedule.
- `roles`: custom role name and granted actions. Protected defaults, memberships and
  machine scope bindings are excluded. Machine grants remain narrowed until local
  scopes are assigned through the existing role editor.
- `loan_policy`: existing loan periods, limits, renewals and reminder policy.
  `null` denotes unconfigured legacy defaults; a configured row remains explicit
  even when its numbers equal the defaults, because its presence enables the ladder.
- `membership_plans`: named plan definitions, intervals, policy prices/currencies and
  loan limits. No member terms, balances, fees already owed or transaction records.
- `admission_policy`: configured settings, form schema and default-plan name.
  Answers, applications, vouches and invitations are excluded. The policy and its
  legacy aliases must agree. Feature switches preserve later operator opt-outs.
- `active_waiver`: current waiver version and authored text, published through the
  normal waiver service. History, signatures and member acceptances never travel.
  An existing version cannot be replaced or reactivated; publish a new version.
- `booking_rules`: active room name and existing duration/lead/advance/approval rules.
  No bookings, booker identity, machine binding, physical location or public token.
  An absent target gets a private generic room; its booking rules use the normal service.
- `notification_defaults`, `email_mutes`: space-wide matrix overrides/mutes.
  No destinations, endpoints, recipients, member preferences, delivery logs or secrets.
  Defaults for uninstalled channels are omitted from export.
- `email_templates`, `chat_templates`: operator-authored, registry-validated text;
  chat is staff-only. No rendered messages or member data. Disabled email streams
  are omitted from export. Review authored text for private information before sharing.
- `categories`, `item_templates`: catalogue metadata and loan/visibility settings.
  Product category references are slugs; admission plan references are names.
  No stock quantities, boxes, assets, QR values, storage locations or image object keys.

Import adds or updates entries by these local natural keys. Entries absent from the
pack are retained; nothing deletes history or assigned roles. Missing references and
duplicate natural names refuse the preview. An archived product/inactive room match
is refused rather than reactivated. New catalogue entries use existing serializers
and start at model-default zero stock; existing quantities are untouched.

Saved profiles have no tenant or User FK. Actor attribution is in platform audit.
`makerspaces.SpacePackProfile` is explicitly omitted from data export and DROP in the
tenant-dump catalogue via `OMITTED_MODELS`; its fields are in the literal Lane D
snapshot, and its JSON never becomes imported tenant authority. This is intentionally
separate from `spaceworks-tenant-dump-v1`, signed backup manifests and dump projections.

Database tests are written in `backend/tests/makerspaces/test_space_pack_*.py` for
the coordinator's isolated runner. The lane does not regenerate OpenAPI artifacts.
