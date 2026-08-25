"""Which admin models are makerspace-scoped, and how each one reaches its tenant.

Split out of :mod:`config.admin_access` so the middleware and the ModelAdmin mixin stay
readable; both names are re-exported there, which is where every caller imports them.
"""

# Models whose makerspace is reached via a nested relation (no direct `makerspace` FK).
# Keyed by "app_label.model_name" (lowercase) -> ORM lookup ending in _id.
NESTED_MAKERSPACE_LOOKUPS = {
    "accounts.memberclaimcode": "membership__makerspace_id",
    "accounts.oidcbrowserattempt": "intended_membership__makerspace_id",
    "makerspaces.membershiprequest": "makerspace_id",
    "makerspaces.makerspacewaiver": "makerspace_id",
    # Profiles hang off the membership, so the membership is the only end of the row
    # that names a tenant.
    "makerspaces.memberprofile": "membership__makerspace_id",
    "makerspaces.memberproject": "profile__membership__makerspace_id",
    "maintenance.maintenanceschedule": "machine__makerspace_id",
    "maintenance.maintenancelog": "machine__makerspace_id",
    "maintenance.maintenancelogdocument": "log__machine__makerspace_id",
    "hardware_requests.hardwarerequestitemasset": "asset__makerspace_id",
    "warranty.warrantydocument": "warranty__makerspace_id",
    "procurement.tobuyreceipt": "to_buy_item__makerspace_id",
    "machines.machineoperator": "machine__makerspace_id",
    "machines.machineusageentry": "machine__makerspace_id",
    "machines.machinedocument": "machine__makerspace_id",
    "machines.machineerrorlog": "machine__makerspace_id",
    "machines.machineconsumable": "machine__makerspace_id",
    "machines.servicebucket": "machine__makerspace_id",
    "machines.servicerequestconsumption": "service_request__makerspace_id",
    # Scoped through the ROLE, not the machine: a type link may point at a global
    # built-in type that belongs to no makerspace, so the role is the only end of the
    # row that always names a tenant.
    "machines.rolemachinetypescope": "role__makerspace_id",
    "machines.rolemachinescope": "role__makerspace_id",
    "bookings.booking": "space__makerspace_id",
    "presence.presencesession": "makerspace_id",
    "payments.makerspacepaymentsettings": "makerspace_id",
    "tenant_migration.disclosureclosureapproval": "makerspace_id",
    "tenant_migration.tenantmigrationexportjob": "export_job__makerspace_id",
}

# Registered admin models that are intentionally NOT makerspace-scoped (account/global).
GLOBAL_ADMIN_MODELS = {
    "accounts.user",
    "organizations.organization",
    "organizations.organizationmembership",
    "accounts.platformsocialauthsettings",
    # The login-method switches govern credentials, and credentials resolve before a
    # makerspace is selected — the same reason social auth is platform-scoped.
    "accounts.platformloginmethods",
    "accounts.passwordresetenvelope",
    "accounts.socialidentity",
    # Platform-scoped for the same reason as the built-in providers: identity resolves
    # before a makerspace is selected, so an OIDC provider cannot belong to one.
    "accounts.oidcprovider",
    "auth.group",
    "axes.accessattempt",
    "axes.accessfailurelog",
    "axes.accesslog",
    "integrations.platformemailsettings",
    "integrations.platformpushsettings",
    # Platform-scoped for the same reason identity is: a sign-in code is sent before any
    # makerspace has been selected, so there is no tenant to own the credentials.
    "integrations.platformsmssettings",
    "integrations.dailyotpsmscounter",
    "payments.platformstripeconnectsettings",
    "updates.platformupdatesettings",
    "backup.platformbackupsettings",
    "backup.backuparchive",
    "backup.restoreoperation",
    "backup.deploymentrecoverystate",
    "backup.deploymentdatabaseidentity", "backup.backuplease",
    "backup.backuprun", "backup.backupruncoverage",
    "backup.restorerollbackobject",
    # Fingerprint reservations are deliberately deployment-global and permanent:
    # `makerspace_id_snapshot` is a plain integer, not an FK, so a reservation
    # outlives its makerspace and cannot be reused. There is no Makerspace path.
    "backup.archiverecipientreservation",
    # Custody state is a deployment backup alarm, scoped like its siblings above
    # (`backuparchive`, `restoreoperation`): an operator must be able to see that a
    # makerspace is below its archive-recipient floor in order to act on it.
    "backup.makerspacearchivecustodystate",
    "backup.archivecustodyalarmdelivery",
    "backup.makerspacetenantexitcustodystate",
    "backup.tenantexitcustodyalarmdelivery",
    "tenant_migration.tenantdumpcapture",
    "backup.b1activationstate", "backup.backupartifactledger",
    "backup.backupartifactcomponent", "backup.backupcomponentrecipient",
    "backup.b1restoreoperationstate", "backup.b1restorecomponentstate",
    "backup.b1reservationentry", "backup.b1fencecontinuity",
    "encryption.piiglobalwritefence",
    "token_blacklist.blacklistedtoken",
    "token_blacklist.outstandingtoken",
}
