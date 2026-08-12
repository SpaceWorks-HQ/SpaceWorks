import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge, Skeleton } from "../../../components/ui";
import {
  collectionResults,
  createMachineType,
  getMachineTypePricing,
  getMachineTypes,
  machineKeys,
  setMachineTypePricing,
  updateMachineType,
  type MachineType,
  type MachineTypeCapabilityConfig,
  type MeteringUnit,
} from "../machinesApi";

const meteringUnits: Array<{ value: MeteringUnit; label: string }> = [
  { value: "weight", label: "Weight (grams)" },
  { value: "volume", label: "Volume (milliliters)" },
  { value: "length", label: "Length (millimeters)" },
  { value: "count", label: "Count" },
  { value: "minutes", label: "Minutes" },
];
const defaultConfig: MachineTypeCapabilityConfig = { metering_unit: "count", requires_booking: false };

function configFor(machineType: MachineType): MachineTypeCapabilityConfig {
  const config = machineType.capability_config;
  return config && meteringUnits.some((unit) => unit.value === config.metering_unit)
    ? config
    : defaultConfig;
}

function PricingEditor({ makerspaceId, machineType, currency, canConfigure }: {
  makerspaceId: number; machineType: MachineType; currency: string; canConfigure: boolean;
}) {
  const queryClient = useQueryClient();
  const pricing = useQuery({ queryKey: machineKeys.pricing(makerspaceId), queryFn: () => getMachineTypePricing(makerspaceId), enabled: canConfigure });
  const row = pricing.data?.results.find((item) => item.machine_type_id === machineType.id);
  const [rate, setRate] = useState("");
  const [flatFee, setFlatFee] = useState("");
  const [paymentEnabled, setPaymentEnabled] = useState<boolean | null>(null);
  const mutation = useMutation({
    mutationFn: () => setMachineTypePricing(makerspaceId, machineType.id, {
      rate_per_unit: rate || row?.rate_per_unit || "0.00",
      flat_fee: flatFee || row?.flat_fee || "0.00",
      payment_enabled: paymentEnabled ?? row?.payment_enabled ?? false,
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: machineKeys.pricing(makerspaceId) }),
  });
  const shownRate = rate || row?.rate_per_unit || "0.00";
  const shownFlatFee = flatFee || row?.flat_fee || "0.00";
  const shownEnabled = paymentEnabled ?? row?.payment_enabled ?? false;

  if (!canConfigure) return null;
  return <div className="grid gap-2 rounded-lg bg-bg p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-end">
    <label className="eyebrow grid gap-1">Rate per unit ({currency})
      <input className="desk-input" type="number" min="0" step="0.01" value={shownRate} onChange={(event) => setRate(event.target.value)} />
    </label>
    <label className="eyebrow grid gap-1">Flat fee ({currency})
      <input className="desk-input" type="number" min="0" step="0.01" value={shownFlatFee} onChange={(event) => setFlatFee(event.target.value)} />
    </label>
    <label className="eyebrow flex items-center gap-2"><input type="checkbox" checked={shownEnabled} onChange={(event) => setPaymentEnabled(event.target.checked)} /> Enable payment</label>
    <button className="desk-button-primary" type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending}>{mutation.isPending ? "Saving..." : "Save pricing"}</button>
    {pricing.isLoading ? <p className="text-xs text-muted md:col-span-4">Loading pricing...</p> : null}
    {pricing.error instanceof Error ? <p className="text-xs text-danger md:col-span-4">{pricing.error.message}</p> : null}
    {mutation.isSuccess ? <p className="text-xs text-success md:col-span-4">Pricing saved.</p> : null}
    {mutation.error instanceof Error ? <p className="text-xs text-danger md:col-span-4">{mutation.error.message}</p> : null}
  </div>;
}

function CustomTypeRow({ makerspaceId, machineType, canConfigure, currency }: {
  makerspaceId: number; machineType: MachineType; canConfigure: boolean; currency: string;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(machineType.name);
  const [icon, setIcon] = useState(machineType.icon);
  const [config, setConfig] = useState(configFor(machineType));
  const rename = useMutation({
    mutationFn: () => updateMachineType(makerspaceId, machineType.id, { name: name.trim(), icon: icon.trim(), capability_config: config }),
    onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: machineKeys.types(makerspaceId) }), queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) })]); },
  });
  return <div className="border-t border-line p-3 first:border-t-0">
    <form className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end" onSubmit={(event) => { event.preventDefault(); rename.mutate(); }}>
      <label className="eyebrow grid gap-1">Name<input className="desk-input" value={name} disabled={!canConfigure} onChange={(event) => setName(event.target.value)} required /></label>
      <label className="eyebrow grid gap-1">Icon<input className="desk-input" value={icon} disabled={!canConfigure} onChange={(event) => setIcon(event.target.value)} placeholder="Optional icon" /></label>
      <label className="eyebrow grid gap-1">Metering unit<select className="desk-input" value={config.metering_unit} disabled={!canConfigure} onChange={(event) => setConfig({ ...config, metering_unit: event.target.value as MeteringUnit })}>{meteringUnits.map((unit) => <option key={unit.value} value={unit.value}>{unit.label}</option>)}</select></label>
      {canConfigure ? <button className="desk-button-primary" type="submit" disabled={rename.isPending || !name.trim()}>{rename.isPending ? "Saving..." : "Save type"}</button> : null}
      <label className="eyebrow flex items-center gap-2 md:col-span-4"><input type="checkbox" checked={config.requires_booking} disabled={!canConfigure} onChange={(event) => setConfig({ ...config, requires_booking: event.target.checked })} /> Requires booking</label>
      <p className="text-xs text-muted md:col-span-4">Slug: {machineType.slug} (fixed)</p>
      {rename.error instanceof Error ? <p className="text-sm text-danger md:col-span-4">{rename.error.message}</p> : null}
    </form>
    <PricingEditor makerspaceId={makerspaceId} machineType={machineType} currency={currency} canConfigure={canConfigure} />
  </div>;
}

export function MachineTypesPanel({ makerspaceId, canConfigureMachineTypes }: { makerspaceId: number; canConfigureMachineTypes: boolean }) {
  const queryClient = useQueryClient();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [icon, setIcon] = useState("");
  const [config, setConfig] = useState(defaultConfig);
  const machineTypes = useQuery({ queryKey: machineKeys.types(makerspaceId), queryFn: () => getMachineTypes(makerspaceId) });
  const pricing = useQuery({ queryKey: machineKeys.pricing(makerspaceId), queryFn: () => getMachineTypePricing(makerspaceId), enabled: canConfigureMachineTypes });
  const create = useMutation({
    mutationFn: () => createMachineType(makerspaceId, { slug: slug.trim(), name: name.trim(), icon: icon.trim(), capability_config: config }),
    onSuccess: async () => { setSlug(""); setName(""); setIcon(""); setConfig(defaultConfig); await queryClient.invalidateQueries({ queryKey: machineKeys.types(makerspaceId) }); },
  });
  const types = collectionResults(machineTypes.data);
  const currency = pricing.data?.currency ?? "Currency";

  return <details className="mb-4 overflow-hidden rounded-xl border border-line bg-panel">
    <summary className="cursor-pointer bg-surface px-3 py-2 text-sm font-semibold text-ink">Machine types and pricing</summary>
    <div className="grid gap-3 p-3">
      <p className="text-sm text-muted">Structural configuration is fixed for built-in types. Prices are makerspace-specific and use the default currency shown beside each amount.</p>
      {canConfigureMachineTypes ? <form className="grid gap-2 rounded-xl border border-line bg-bg p-3 md:grid-cols-4 md:items-end" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
        <label className="eyebrow grid gap-1">Slug<input className="desk-input" value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="laser-cutter" required /></label>
        <label className="eyebrow grid gap-1">Name<input className="desk-input" value={name} onChange={(event) => setName(event.target.value)} placeholder="Laser cutter" required /></label>
        <label className="eyebrow grid gap-1">Icon<input className="desk-input" value={icon} onChange={(event) => setIcon(event.target.value)} placeholder="Optional icon" /></label>
        <label className="eyebrow grid gap-1">Metering unit<select className="desk-input" value={config.metering_unit} onChange={(event) => setConfig({ ...config, metering_unit: event.target.value as MeteringUnit })}>{meteringUnits.map((unit) => <option key={unit.value} value={unit.value}>{unit.label}</option>)}</select></label>
        <label className="eyebrow flex items-center gap-2"><input type="checkbox" checked={config.requires_booking} onChange={(event) => setConfig({ ...config, requires_booking: event.target.checked })} /> Requires booking</label>
        <button className="desk-button-primary" type="submit" disabled={create.isPending || !slug.trim() || !name.trim()}>{create.isPending ? "Creating..." : "Create type"}</button>
        {create.error instanceof Error ? <p className="text-sm text-danger md:col-span-4">{create.error.message}</p> : null}
      </form> : <p className="text-sm text-muted">You have read-only access to machine types and pricing.</p>}
      {machineTypes.isLoading ? <Skeleton className="h-20 w-full" /> : null}
      {machineTypes.error instanceof Error ? <p className="text-sm text-danger">{machineTypes.error.message}</p> : null}
      {types.length ? <div className="overflow-hidden rounded-xl border border-line">{types.map((machineType) => machineType.is_builtin || machineType.makerspace === null ? <div key={machineType.id} className="grid gap-2 border-t border-line p-3 first:border-t-0"><div className="flex flex-wrap items-center justify-between gap-2"><span><strong className="block text-sm text-ink">{machineType.name}</strong><span className="text-xs text-muted">{machineType.icon || "No icon"} · {machineType.slug} · {configFor(machineType).metering_unit} · {configFor(machineType).requires_booking ? "booking required" : "no booking"}</span></span><Badge tone="neutral">Built-in · structural config read-only</Badge></div><PricingEditor makerspaceId={makerspaceId} machineType={machineType} currency={currency} canConfigure={canConfigureMachineTypes} /></div> : <CustomTypeRow key={machineType.id} makerspaceId={makerspaceId} machineType={machineType} canConfigure={canConfigureMachineTypes} currency={currency} />)}</div> : null}
    </div>
  </details>;
}
