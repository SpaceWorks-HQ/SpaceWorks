import { useQuery } from "@tanstack/react-query";

import { Panel, type Makerspace } from "./panels/shared";
import { TenantMigrationDisclosure } from "./TenantMigrationDisclosure";
import { TenantMigrationExports } from "./TenantMigrationExports";
import { TenantMigrationImports } from "./TenantMigrationImports";
import { TenantMigrationPairings } from "./TenantMigrationPairings";
import {
  getDisclosureClosure,
  listPairings,
  tenantMigrationKeys,
} from "./tenantMigrationApi";
import { ErrorText } from "./tenantMigrationUi";

export function TenantMigrationPanel({ makerspace }: { makerspace: Makerspace }) {
  const closure = useQuery({
    queryKey: tenantMigrationKeys.closure(makerspace.id),
    queryFn: () => getDisclosureClosure(makerspace.id),
  });
  const pairings = useQuery({
    queryKey: tenantMigrationKeys.pairings,
    queryFn: listPairings,
  });

  return (
    <Panel title="Tenant migration">
      <div className="grid gap-4">
        <div className="rounded-md border border-danger/40 bg-danger/10 p-4">
          <p className="eyebrow text-danger">Superadmin-only irreversible workflow</p>
          <p className="mt-2 text-sm text-ink">
            Move one makerspace from a managed deployment to a self-hosted deployment. Review
            disclosure, encrypt the export for the target, resolve every identity, verify the
            materialized tenant, then complete the signed two-key cutover.
          </p>
          <p className="mt-2 text-sm font-semibold text-danger">
            Cutover archives the source tenant; it does not delete it. Archives are outside the purge guarantee.
          </p>
        </div>
        <TenantMigrationDisclosure makerspaceId={makerspace.id} />
        <TenantMigrationExports
          makerspaceId={makerspace.id}
          tenantName={makerspace.name}
          closureDigest={closure.data?.digest}
          pairings={pairings.data ?? []}
        />
        <TenantMigrationPairings pairings={pairings.data ?? []} />
        <TenantMigrationImports pairings={pairings.data ?? []} />
        {pairings.isLoading ? <p className="text-sm text-muted">Loading pinned deployment pairings…</p> : null}
        <ErrorText error={pairings.error} />
      </div>
    </Panel>
  );
}
