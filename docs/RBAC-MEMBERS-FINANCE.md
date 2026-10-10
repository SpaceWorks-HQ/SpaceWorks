# Member and finance delegation (F6)

Roles remain editable, local to one makerspace, and action based. The four protected
defaults are unchanged. Presets in the custom-role editor only prefill a name and grants;
staff must save the role and assign it before anyone receives authority.

| Action | Grants |
| --- | --- |
| `manage_members` | Roster and request queues, community invitations and approvals, verification/referral delegation, witnessed waiver acceptance, plan reads and term assignment/cancellation. Implies `manage_member_cards`, which implies `scan_member_cards`. |
| `view_finance` | Full payment ledger, settlement receipts, payment reconciliation report and exports. Does not grant cash recording, waivers or refunds. |
| `record_payment` | Offline settlements, receipt corrections, and offline refund receipts across the makerspace's charge subjects. Does not grant settings, debt waivers or online refunds. |

Membership Coordinator holds `manage_members`. Treasurer holds `view_finance` and
`record_payment`. Front-desk cashier holds `record_payment` and the handout actions,
including collection of completed machine-service jobs. It retains the narrow handover
console with a Payments tab.

Membership Coordinators may assign only action-less community roles and cannot remove or
replace a staff member's grants. Staff role creation, staff account provisioning,
makerspace settings, membership plan definitions/prices and waiver publishing remain
`manage_makerspace` operations. Coordinators can read plans and assign their terms.
Membership-only roster responses do not include payment summaries.
Coordinators cannot approve or cancel an existing staff invitation by substituting a
community role. Verification and term controls remain available on staff roster rows;
changing or revoking the staff role still requires makerspace administration.

The roster uses `view_finance` for money visibility, `record_payment` for cash recording,
and the existing membership-subject authority for waiving a debt. A read-only finance
grant shows amounts without payment mutation controls. The report console uses the same
finance grant to render money reports without loading unauthorized hardware summaries.

The full payment list requires `view_finance`. A cashier uses the same route with
`for_recording=true`: it requires `record_payment` and returns pending and offline-settled
charges needed for receipt work. The query cache distinguishes these scopes. Money
reports still require `view_finance`. The ledger and cash recording work with the online
`payments` module off; the `reports` and `membership` module gates remain unchanged.

Existing charge-domain staff retain their scoped cash recording paths. Debt waivers and
online refunds retain their existing subject authority and machine scoping. Finance
authority never implies machine lifecycle authority.

Migration `makerspaces.0077_member_finance_actions` adds all three new actions to every
stored role containing `manage_makerspace`, including custom roles.
Organization memberships holding that action receive the same additive backfill, without
changing link reach, membership identity or hidden-space exclusions. New Space Manager
defaults and the legacy null-role fallback include them. Inventory Manager and Member
receive no new grants. `manage_makerspace` has no new dynamic implication: administrators
can edit the actions independently after the backfill. The additive migration has a
no-op reverse to avoid removing later administrator grants.

All routes continue to use the central RBAC makerspace scope, active-account checks,
tenant-origin restrictions and superadmin-hidden fences. Cash and membership mutations
retain their transaction and audit services. No model, module or feature key was added.
