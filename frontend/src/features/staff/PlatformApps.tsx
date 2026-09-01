import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Card, Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { PublicInventoryPage } from "../inventory/PublicInventoryPage";
import { StaffApp } from "./StaffApp";

type ResolveResult = {
  target: Record<string, string | number>;
  allowed_actions: string[];
};

export function KioskPage() {
  const { slug } = useParams();
  return (
    <main className="desk-shell">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3">
          <div>
            <SpaceWorksBadge className="mb-3" />
            <p className="text-xs font-semibold tracking-wide text-accent-ink">
              Kiosk
            </p>
            <h1 className="text-xl font-bold text-ink">Public desk</h1>
          </div>
          <div className="flex gap-2">
            <ThemeToggle />
            <Link className="desk-button" to={`/m/${slug ?? ""}`}>
              Catalog
            </Link>
          </div>
        </div>
      </header>
      <PublicInventoryPage />
    </main>
  );
}

export function ScannerPage() {
  const [payload, setPayload] = useState("");
  const resolve = useMutation({
    mutationFn: () =>
      staffRequest<ResolveResult>("/admin/qr/resolve", {
        method: "POST",
        body: JSON.stringify({ payload: payload.trim() }),
      }),
  });
  return (
    <main className="desk-shell grid place-items-start px-5 py-6">
      <section className="mx-auto w-full max-w-3xl space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <SpaceWorksBadge className="mb-3" />
            <p className="text-xs font-semibold tracking-wide text-accent-ink">
              Scanner
            </p>
            <h1 className="text-2xl font-bold text-ink">QR resolution</h1>
          </div>
          <ThemeToggle />
        </div>
        <Card>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Field className="flex-1" label="QR payload">
              <input
                className="desk-input flex-1"
                placeholder="Scan or paste QR payload"
                value={payload}
                onChange={(event) => setPayload(event.target.value)}
              />
            </Field>
            <button
              className="desk-button-primary"
              disabled={!payload.trim() || resolve.isPending}
              onClick={() => resolve.mutate()}
            >
              Resolve
            </button>
          </div>
          {resolve.isError ? (
            <p className="mt-3 text-sm text-danger">{resolve.error.message}</p>
          ) : null}
          {resolve.data ? (
            <div className="mt-4 grid gap-3">
              <pre className="overflow-auto rounded-md border border-line bg-bg p-3 text-xs text-muted">
                {JSON.stringify(resolve.data.target, null, 2)}
              </pre>
              <div className="flex flex-wrap gap-2">
                {resolve.data.allowed_actions.map((action) => (
                  <span key={action} className="rounded-md border border-line bg-surface px-2 py-1 text-xs text-muted">
                    {action}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </Card>
      </section>
    </main>
  );
}

export function SuperadminPage() {
  return <StaffApp />;
}
