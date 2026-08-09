import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { Panel, useStaffGet } from "./panels/shared";

type ModuleRow = {
  key: string;
  label: string;
  description: string;
  installed: boolean;
  core: boolean;
  available: boolean;
  requires: string[];
  pulls_in: string[];
  required_by: string[];
  workflows: string[];
};

type ModuleGroup = {
  key: string;
  label: string;
  description: string;
  always_on: boolean;
  installed_count: number;
  module_count: number;
  modules: ModuleRow[];
};

type DeploymentApp = { app_label: string; shipped: boolean; note: string };

type ModulesResponse = {
  groups: ModuleGroup[];
  deployment: { apps: DeploymentApp[]; env_line: string; requires_restart: boolean };
};

const errorText = (error: unknown) =>
  error instanceof StructuredApiError ? error.detail ?? error.message : "Unable to change modules.";

export function ModulesPanel({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const queryKey = ["modules", makerspaceId];
  const modules = useStaffGet<ModulesResponse>(queryKey, `/admin/makerspace/${makerspaceId}/modules`);
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  const change = useMutation({
    mutationFn: ({ key, action }: { key: string; action: "install" | "uninstall" }) =>
      staffRequest(`/admin/makerspace/${makerspaceId}/modules/${action}`, {
        method: "POST",
        body: JSON.stringify({ key }),
      }),
    // The server returns the recomputed groups, but invalidating is what keeps the rest
    // of the console honest: enabled_modules drives every tab gate, so a stale
    // makerspaces query would leave tabs visible for a module just uninstalled.
    onSuccess: () => {
      client.invalidateQueries({ queryKey });
      client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });

  if (modules.isLoading) return <Panel title="Modules">Loading modules…</Panel>;
  if (modules.isError) {
    return (
      <Panel title="Modules">
        <p className="text-sm text-danger" role="alert">{errorText(modules.error)}</p>
      </Panel>
    );
  }

  const groups = modules.data?.groups ?? [];
  const deployment = modules.data?.deployment;

  return (
    <div className="grid gap-5">
      <Panel title="Modules">
        <p className="mb-4 text-sm text-muted">
          Installing a module switches its surfaces on for this makerspace. Uninstalling clears
          the capability only — rows, uploads and history are kept, and reinstalling restores
          everything. Deleting the data is a separate step run from the command line.
        </p>
        {change.isError ? (
          <p className="mb-3 text-sm text-danger" role="alert">{errorText(change.error)}</p>
        ) : null}
        <div className="grid gap-3">
          {groups.map((group) => {
            const open = openGroup === group.key;
            return (
              <section key={group.key} className="rounded-md border border-line bg-surface">
                <button
                  type="button"
                  aria-expanded={open}
                  className="flex w-full flex-wrap items-center justify-between gap-3 p-3 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                  onClick={() => setOpenGroup(open ? null : group.key)}
                >
                  <span>
                    <span className="font-semibold text-ink">{group.label}</span>
                    <span className="block text-sm text-muted">{group.description}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {group.always_on ? (
                      <Badge tone="neutral">Always on</Badge>
                    ) : (
                      <Badge tone={group.installed_count ? "success" : "neutral"}>
                        {`${group.installed_count} of ${group.module_count} installed`}
                      </Badge>
                    )}
                  </span>
                </button>
                {/* Unmounted rather than hidden: a keyboard user must not be able to tab
                    into an Install button they cannot see. */}
                {open ? (
                  <div className="border-t border-line p-3">
                    {group.modules.map((module) => (
                      <ModuleCard
                        key={module.key}
                        module={module}
                        pending={change.isPending}
                        onChange={(action) => change.mutate({ key: module.key, action })}
                      />
                    ))}
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>
      </Panel>

      {deployment ? (
        <Panel title="Deployment">
          <p className="mb-3 text-sm text-muted">
            These apps can be removed from the build entirely, which drops their routes, admin
            screens and API schema for every makerspace. It is read from the environment at
            start-up, so this is a copyable line rather than a switch — the running process
            cannot change it without a restart.
          </p>
          <div className="grid gap-2">
            {deployment.apps.map((app) => (
              <div
                key={app.app_label}
                className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2"
              >
                <span>
                  <span className="font-mono text-sm text-ink">{app.app_label}</span>
                  {app.note ? <span className="block text-xs text-muted">{app.note}</span> : null}
                </span>
                <Badge tone={app.shipped ? "success" : "neutral"}>
                  {app.shipped ? "Shipped" : "Removed"}
                </Badge>
              </div>
            ))}
          </div>
          <pre className="mt-3 overflow-x-auto rounded-md border border-line bg-bg p-3 text-xs text-ink">
            {deployment.env_line}
          </pre>
        </Panel>
      ) : null}
    </div>
  );
}

function ModuleCard({
  module,
  pending,
  onChange,
}: {
  module: ModuleRow;
  pending: boolean;
  onChange: (action: "install" | "uninstall") => void;
}) {
  const blocked = module.required_by.length > 0;
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-t border-line py-3 first:border-t-0">
      <div className="min-w-0">
        <p className="font-semibold text-ink">{module.label}</p>
        <p className="text-sm text-muted">{module.description}</p>
        {module.workflows.length ? (
          <p className="mt-1 text-xs text-muted">Turns on: {module.workflows.join(", ")}</p>
        ) : null}
        {/* Shown before the click: a dependency resolved silently is a capability the
            operator did not choose. */}
        {!module.installed && module.pulls_in.length ? (
          <p className="mt-1 text-xs text-muted">Also installs: {module.pulls_in.join(", ")}</p>
        ) : null}
        {blocked ? (
          <p className="mt-1 text-xs text-muted">Required by {module.required_by.join(", ")}</p>
        ) : null}
        {!module.available ? (
          <p className="mt-1 text-xs text-muted">Not shipped by this deployment.</p>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        {module.core ? (
          <Badge tone="neutral">Core</Badge>
        ) : module.installed ? (
          <button
            type="button"
            className="desk-button"
            disabled={pending || blocked}
            onClick={() => onChange("uninstall")}
          >
            Uninstall
          </button>
        ) : (
          <button
            type="button"
            className="desk-button-primary"
            disabled={pending || !module.available}
            onClick={() => onChange("install")}
          >
            Install
          </button>
        )}
      </div>
    </div>
  );
}
