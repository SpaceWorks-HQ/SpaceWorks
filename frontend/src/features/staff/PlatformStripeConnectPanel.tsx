import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { Panel, useStaffGet } from "./StaffPanels";

type PlatformPaymentSettings = {
  id: number;
  stripe_publishable_key_set: boolean;
  stripe_secret_key_set: boolean;
  stripe_webhook_secret_set: boolean;
  stripe_connect_client_id: string;
  application_fee_bps: number;
  updated_at: string;
};

type RevocableCredential =
  | "stripe_publishable_key"
  | "stripe_secret_key"
  | "stripe_webhook_secret";

export function PlatformStripeConnectPanel() {
  const queryClient = useQueryClient();
  const settings = useStaffGet<PlatformPaymentSettings>(
    ["platform-payment-settings"],
    "/admin/platform/payment-settings",
  );
  const [publishableKey, setPublishableKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [clientId, setClientId] = useState("");
  const [feeBps, setFeeBps] = useState("0");

  useEffect(() => {
    if (!settings.data) return;
    setClientId(settings.data.stripe_connect_client_id ?? "");
    setFeeBps(String(settings.data.application_fee_bps ?? 0));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      staffRequest<PlatformPaymentSettings>("/admin/platform/payment-settings", {
        method: "PATCH",
        body: JSON.stringify({
          stripe_connect_client_id: clientId,
          application_fee_bps: Number(feeBps) || 0,
          ...(publishableKey ? { stripe_publishable_key: publishableKey } : {}),
          ...(secretKey ? { stripe_secret_key: secretKey } : {}),
          ...(webhookSecret ? { stripe_webhook_secret: webhookSecret } : {}),
        }),
      }),
    onSuccess: () => {
      setPublishableKey("");
      setSecretKey("");
      setWebhookSecret("");
      queryClient.invalidateQueries({ queryKey: ["platform-payment-settings"] });
    },
  });
  const clearCredential = useMutation({
    mutationFn: (credential: RevocableCredential) =>
      staffRequest<PlatformPaymentSettings>("/admin/platform/payment-settings", {
        method: "PATCH",
        body: JSON.stringify({ [credential]: "" }),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["platform-payment-settings"] }),
  });
  const busy = settings.isLoading || save.isPending || clearCredential.isPending;

  return (
    <Panel title="Platform Stripe Connect">
      <p className="text-sm text-muted">
        Platform credentials authorize direct charges into each makerspace&apos;s connected account.
      </p>
      <div className="mt-4 rounded-md border border-line bg-surface p-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="Platform publishable key"><input className="desk-input" type="password" autoComplete="new-password" placeholder={settings.data?.stripe_publishable_key_set ? "Platform publishable key set" : undefined} value={publishableKey} onChange={(event) => setPublishableKey(event.target.value)} /></Field>
          <Field label="Platform secret key"><input className="desk-input" type="password" autoComplete="new-password" placeholder={settings.data?.stripe_secret_key_set ? "Platform secret key set" : undefined} value={secretKey} onChange={(event) => setSecretKey(event.target.value)} /></Field>
          <Field label="Platform webhook secret"><input className="desk-input" type="password" autoComplete="new-password" placeholder={settings.data?.stripe_webhook_secret_set ? "Platform webhook secret set" : undefined} value={webhookSecret} onChange={(event) => setWebhookSecret(event.target.value)} /></Field>
          <Field label="Stripe Connect client ID"><input className="desk-input" value={clientId} onChange={(event) => setClientId(event.target.value)} /></Field>
          <input
            aria-label="Application fee basis points"
            className="desk-input"
            inputMode="numeric"
            min={0}
            max={10000}
            type="number"
            value={feeBps}
            onChange={(event) => setFeeBps(event.target.value)}
          />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="desk-button-primary flex-1"
            disabled={busy}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving..." : "Save Stripe Connect settings"}
          </button>
          <button
            className="desk-button"
            disabled={!settings.data?.stripe_publishable_key_set || busy}
            onClick={() => clearCredential.mutate("stripe_publishable_key")}
          >
            Clear publishable key
          </button>
          <button
            className="desk-button"
            disabled={!settings.data?.stripe_secret_key_set || busy}
            onClick={() => clearCredential.mutate("stripe_secret_key")}
          >
            Clear secret key
          </button>
          <button
            className="desk-button"
            disabled={!settings.data?.stripe_webhook_secret_set || busy}
            onClick={() => clearCredential.mutate("stripe_webhook_secret")}
          >
            Clear webhook secret
          </button>
        </div>
        <p className="mt-2 text-sm text-muted">
          Application fee: {settings.data?.application_fee_bps ?? 0} basis points. Saved keys are never returned.
        </p>
        {settings.error || save.error || clearCredential.error ? (
          <p className="mt-2 text-sm text-danger" role="alert">
            {(settings.error || save.error || clearCredential.error)?.message}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
