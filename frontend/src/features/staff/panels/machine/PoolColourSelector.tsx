import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { PrinterPool } from "../../../../generated/api";
import { staffRequest, type StaffAuthUser } from "../../../../lib/api";
import { machineKeys, updateMachineType, type MachineType } from "../../machinesApi";
import { PoolColourSwatchControl } from "./PoolColourSwatchControl";

type Props = {
  makerspaceId: number;
  machineType?: MachineType;
  existingPools: PrinterPool[];
  value: string;
  valueHex: string;
  onSelect: (name: string, hex: string) => void;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const commonColourHex: Record<string, string> = {
  black: "#000000",
  white: "#ffffff",
  red: "#dc2626",
  blue: "#2563eb",
  green: "#16a34a",
  gray: "#6b7280",
  grey: "#6b7280",
  yellow: "#eab308",
  orange: "#ea580c",
  purple: "#9333ea",
  pink: "#db2777",
  clear: "#f8fafc",
  natural: "#e7dcc8",
  "clear/natural": "#f1f5f9",
  silver: "#c0c0c0",
  gold: "#d4af37",
};

const normaliseName = (name: string) => name.trim().toLocaleLowerCase();
const validHex = (value: string | undefined) => /^#[0-9a-f]{6}$/i.test(value?.trim() ?? "");

function latestPoolHexes(pools: PrinterPool[]) {
  const result = new Map<string, string>();
  [...pools]
    .sort((left, right) => right.created_at.localeCompare(left.created_at) || right.id - left.id)
    .forEach((pool) => {
      const name = normaliseName(pool.color ?? "");
      if (name && !result.has(name) && validHex(pool.color_hex)) {
        result.set(name, pool.color_hex!.trim().toLowerCase());
      }
    });
  return result;
}

export function PoolColourSelector({ makerspaceId, machineType, existingPools, value, valueHex, onSelect }: Props) {
  const queryClient = useQueryClient();
  const [addingCustom, setAddingCustom] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customHex, setCustomHex] = useState("#000000");
  const [customError, setCustomError] = useState("");
  const [addedColours, setAddedColours] = useState<Array<{ name: string; hex: string }>>([]);
  const configuredColours = machineType?.capability_config?.accepted_colours ?? [];
  const colourNames = useMemo(() => {
    const names = new Map<string, string>();
    [...configuredColours, ...addedColours.map(({ name }) => name)].forEach((name) => {
      if (!names.has(normaliseName(name))) names.set(normaliseName(name), name);
    });
    return [...names.values()];
  }, [addedColours, configuredColours]);
  const poolHexes = useMemo(() => latestPoolHexes(existingPools), [existingPools]);
  const localHexes = useMemo(
    () => new Map(addedColours.map(({ name, hex }) => [normaliseName(name), hex])),
    [addedColours],
  );
  const currentUser = useQuery({
    queryKey: ["staff", "me"],
    queryFn: () => staffRequest<StaffAuthUser>("/auth/me"),
    enabled: Boolean(machineType),
  });
  const canConfigure = Boolean(
    currentUser.data?.is_superuser ||
    currentUser.data?.makerspaces?.find(({ id }) => id === makerspaceId)?.can_configure_machine_types,
  );
  const appendColour = useMutation({
    mutationFn: ({ name }: { name: string; hex: string }) => {
      if (!machineType) throw new Error("A machine type is required.");
      const capabilityConfig = machineType.capability_config ?? { metering_unit: "count", requires_booking: false };
      return updateMachineType(makerspaceId, machineType.id, {
        name: machineType.name,
        icon: machineType.icon,
        capability_config: { ...capabilityConfig, accepted_colours: [...colourNames, name] },
      });
    },
    onSuccess: async (_updatedType, custom) => {
      setAddedColours((current) => [...current, custom]);
      onSelect(custom.name, custom.hex);
      setCustomName("");
      setCustomHex("#000000");
      setCustomError("");
      setAddingCustom(false);
      await queryClient.invalidateQueries({ queryKey: machineKeys.types(makerspaceId) });
    },
  });

  const confirmCustom = () => {
    const name = customName.trim();
    if (!name) {
      setCustomError("Colour name cannot be blank.");
      return;
    }
    if (colourNames.some((colour) => normaliseName(colour) === normaliseName(name))) {
      setCustomError("Colour name already exists.");
      return;
    }
    setCustomError("");
    appendColour.mutate({ name, hex: customHex });
  };

  const hexFor = (name: string) => {
    const key = normaliseName(name);
    return poolHexes.get(key) ?? commonColourHex[key] ?? localHexes.get(key) ?? "";
  };

  return (
    <div className="grid gap-3">
      {configuredColours.length ? (
        <fieldset className="grid gap-2 rounded-xl border border-line p-3">
          <legend className="eyebrow px-1">Colour</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {colourNames.map((name) => {
              const hex = hexFor(name);
              const selected = normaliseName(value) === normaliseName(name);
              return (
                <button
                  aria-pressed={selected}
                  className={`desk-button relative grid h-auto min-h-11 items-stretch justify-stretch gap-0 overflow-hidden bg-bg p-0 text-left ${focusRing} ${selected ? "border-2 border-accent shadow-soft" : "border border-line"}`}
                  key={normaliseName(name)}
                  type="button"
                  onClick={() => onSelect(name, hex)}
                >
                  {hex ? <span aria-hidden="true" className="h-10 border-b border-line" style={{ backgroundColor: hex }} /> : null}
                  <span className={`flex min-h-11 items-center justify-between gap-2 px-2 py-1 text-sm font-semibold text-ink ${hex ? "bg-bg" : "bg-surface"}`}>
                    <span>{name}</span>
                    {selected ? <span aria-hidden="true" className="text-accent-ink">✓</span> : null}
                  </span>
                </button>
              );
            })}
          </div>
        </fieldset>
      ) : (
        <label className="eyebrow grid gap-1">
          Colour
          <input
            className="desk-input"
            value={value}
            onChange={(event) => onSelect(event.target.value, valueHex)}
            placeholder="e.g. Signal red"
          />
        </label>
      )}

      {!configuredColours.length ? (
        <PoolColourSwatchControl value={valueHex} onChange={(hex) => onSelect(value, hex)} />
      ) : null}

      {canConfigure && machineType ? (
        addingCustom ? (
          <fieldset className="grid gap-3 rounded-xl border border-line bg-surface p-3">
            <legend className="eyebrow px-1">Add custom colour</legend>
            <label className="eyebrow grid gap-1">
              Custom colour name
              <input
                aria-describedby={customError ? "custom-colour-error" : undefined}
                className="desk-input"
                value={customName}
                onChange={(event) => { setCustomName(event.target.value); setCustomError(""); appendColour.reset(); }}
              />
            </label>
            <PoolColourSwatchControl legend="Custom colour swatch" value={customHex} onChange={setCustomHex} />
            <div className="flex flex-wrap gap-2">
              <button className="desk-button-primary" disabled={appendColour.isPending} type="button" onClick={confirmCustom}>
                {appendColour.isPending ? "Saving..." : "Save custom colour"}
              </button>
              <button className="desk-button-ghost" type="button" onClick={() => { setAddingCustom(false); setCustomError(""); appendColour.reset(); }}>
                Cancel
              </button>
            </div>
            {customError ? <p className="text-sm text-danger" id="custom-colour-error" role="alert">{customError}</p> : null}
            {appendColour.error instanceof Error ? <p className="text-sm text-danger" role="alert">{appendColour.error.message}</p> : null}
          </fieldset>
        ) : (
          <button className="desk-button-secondary justify-self-start" type="button" onClick={() => setAddingCustom(true)}>
            Add a custom colour
          </button>
        )
      ) : null}
    </div>
  );
}
