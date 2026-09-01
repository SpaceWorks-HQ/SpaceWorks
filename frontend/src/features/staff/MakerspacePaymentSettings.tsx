import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge, Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { type Makerspace, useStaffGet } from "./StaffPanels";

type PaymentSettings = {
  default_currency: string;
  stripe_publishable_key_set: boolean;
  stripe_secret_key_set: boolean;
  stripe_webhook_secret_set: boolean;
  effective_mode: "raw" | "connect" | "unavailable";
  connect_account_id?: string | null;
  connect_status: "unconnected" | "pending" | "active" | "restricted" | "disconnected";
  connect_charges_enabled: boolean;
  connect_payouts_enabled: boolean;
};

export function MakerspacePaymentSettings({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const queryKey = ["payment-settings", makerspace.id];
  const path = `/admin/makerspace/${makerspace.id}/payment-settings`;
  const settings = useStaffGet<PaymentSettings>(queryKey, path);
  const [publishableKey, setPublishableKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [currency, setCurrency] = useState("usd");

  useEffect(() => {
    if (settings.data) setCurrency(settings.data.default_currency);
  }, [settings.data]);

  const refresh = () => queryClient.invalidateQueries({ queryKey });
  const save = useMutation({
    mutationFn: () =>
      staffRequest<PaymentSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({
          default_currency: currency,
          ...(publishableKey ? { stripe_publishable_key: publishableKey } : {}),
          ...(secretKey ? { stripe_secret_key: secretKey } : {}),
          ...(webhookSecret ? { stripe_webhook_secret: webhookSecret } : {}),
        }),
      }),
    onSuccess: () => {
      setPublishableKey("");
      setSecretKey("");
      setWebhookSecret("");
      refresh();
    },
  });
  const clear = useMutation({
    mutationFn: () =>
      staffRequest<PaymentSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({
          stripe_publishable_key: "",
          stripe_secret_key: "",
          stripe_webhook_secret: "",
        }),
      }),
    onSuccess: refresh,
  });
  const onboard = useMutation({
    mutationFn: () =>
      staffRequest<{ authorize_url: string }>(`${path}/connect/onboard`, {
        method: "POST",
      }),
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
  });
  const busy = settings.isLoading || save.isPending || clear.isPending || onboard.isPending;

  return (
    <section className="rounded-md border border-line bg-bg p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-ink">Stripe payments</h3>
          <p className="mt-1 text-sm text-muted">
            Secret credentials are encrypted; saved keys are never displayed again.
          </p>
        </div>
        <Badge tone={settings.data?.effective_mode === "unavailable" ? "neutral" : "success"}>
          {modeLabel(settings.data?.effective_mode)}
        </Badge>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <Field label="Stripe publishable key">
          <input
            className="desk-input"
            type="password"
            autoComplete="new-password"
            placeholder={settings.data?.stripe_publishable_key_set ? "Stripe publishable key set" : undefined}
            value={publishableKey}
            onChange={(event) => setPublishableKey(event.target.value)}
          />
        </Field>
        <Field label="Stripe secret key">
          <input
            className="desk-input"
            type="password"
            autoComplete="new-password"
            placeholder={settings.data?.stripe_secret_key_set ? "Stripe secret key set" : undefined}
            value={secretKey}
            onChange={(event) => setSecretKey(event.target.value)}
          />
        </Field>
        <Field label="Stripe webhook secret">
          <input
            className="desk-input"
            type="password"
            autoComplete="new-password"
            placeholder={settings.data?.stripe_webhook_secret_set ? "Stripe webhook secret set" : undefined}
            value={webhookSecret}
            onChange={(event) => setWebhookSecret(event.target.value)}
          />
        </Field>
        <input
          aria-label="Default payment currency"
          className="desk-input"
          maxLength={3}
          value={currency}
          onChange={(event) => setCurrency(event.target.value.toLowerCase())}
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="desk-button-primary" disabled={busy} onClick={() => save.mutate()}>
          {save.isPending ? "Saving..." : "Save payment settings"}
        </button>
        <button
          className="desk-button"
          disabled={
            busy
            || !(
              settings.data?.stripe_publishable_key_set
              || settings.data?.stripe_secret_key_set
              || settings.data?.stripe_webhook_secret_set
            )
          }
          onClick={() => clear.mutate()}
        >
          Clear raw configuration
        </button>
      </div>
      {makerspace.platform_hosting ? (
        <div className="mt-4 rounded-md border border-line bg-surface p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="font-semibold text-ink">Stripe Connect</p>
              <p className="text-sm text-muted">Status: {settings.data?.connect_status ?? "unconnected"}</p>
            </div>
            <button className="desk-button-primary" disabled={busy} onClick={() => onboard.mutate()}>
              {settings.data?.connect_status === "unconnected" ? "Connect Stripe" : "Reconnect Stripe"}
            </button>
          </div>
          <p className="mt-2 text-sm text-muted">
            A complete raw credential pair takes precedence over Connect; clearing it restores the Connect fallback.
          </p>
        </div>
      ) : null}
      {settings.error || save.error || clear.error || onboard.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {(settings.error || save.error || clear.error || onboard.error)?.message}
        </p>
      ) : null}
    </section>
  );
}

function modeLabel(mode?: PaymentSettings["effective_mode"]) {
  return mode === "raw" ? "Raw credentials" : mode === "connect" ? "Stripe Connect" : "Unavailable";
}
