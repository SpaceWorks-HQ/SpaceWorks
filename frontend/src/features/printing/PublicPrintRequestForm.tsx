import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import { Card } from "../../components/ui/Card";
import { FilePicker, TextArea, TextInput } from "./PublicPrintRequestParts";
import type { PublicFilamentPool } from "./publicApi";

export type FormState = {
  title: string;
  projectBrief: string;
  preferredSettings: string;
  consumablePoolId: string;
  estimatedFilamentGrams: string;
  material: string;
  color: string;
  quantity: number;
  sourceLink: string;
};

export const initialForm: FormState = {
  title: "",
  projectBrief: "",
  preferredSettings: "",
  consumablePoolId: "",
  estimatedFilamentGrams: "",
  material: "",
  color: "",
  quantity: 1,
  sourceLink: "",
};

export function optional(value: string) {
  const trimmed = value.trim();
  return trimmed || undefined;
}

// Group active spools by material so same-material filaments are listed together and
// distinguished by color (the public /spools endpoint already orders by material,color).
export function groupPoolsByMaterial(
  pools: PublicFilamentPool[],
): [string, PublicFilamentPool[]][] {
  const groups = new Map<string, PublicFilamentPool[]>();
  for (const pool of pools) {
    const key = pool.material || "Other";
    const bucket = groups.get(key);
    if (bucket) bucket.push(pool);
    else groups.set(key, [pool]);
  }
  return [...groups.entries()];
}

type PrintDetailsFormProps = {
  form: FormState;
  updateField: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
  poolsQuery: UseQueryResult<PublicFilamentPool[], Error>;
  modelFiles: File[];
  setModelFiles: Dispatch<SetStateAction<File[]>>;
  screenshotFiles: File[];
  setScreenshotFiles: Dispatch<SetStateAction<File[]>>;
  submitPending: boolean;
  submitError?: Error | null;
  uploadProgress: string;
  website: string;
  onWebsiteChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function PrintDetailsForm({
  form,
  updateField,
  poolsQuery,
  modelFiles,
  setModelFiles,
  screenshotFiles,
  setScreenshotFiles,
  submitPending,
  submitError,
  uploadProgress,
  website,
  onWebsiteChange,
  onSubmit,
}: PrintDetailsFormProps) {
  return (
    <Card>
      <h2 className="title-panel text-secondary-ink">
        Print Details
      </h2>
      <form className="mt-4 space-y-4" onSubmit={onSubmit}>
        {/* Honeypot: hidden from humans; bots that autofill it trigger the server decoy. */}
        <input
          aria-hidden="true"
          autoComplete="off"
          className="hidden"
          name="website"
          tabIndex={-1}
          value={website}
          onChange={(event) => onWebsiteChange(event.target.value)}
        />
        <fieldset className="space-y-4" disabled={submitPending}>
          <TextInput
            label="Title"
            required
            value={form.title}
            onChange={(value) => updateField("title", value)}
          />
          <TextArea
            label="Project brief"
            value={form.projectBrief}
            onChange={(value) => updateField("projectBrief", value)}
          />
          <TextArea
            label="Slicer settings / personal preferences"
            value={form.preferredSettings}
            onChange={(value) => updateField("preferredSettings", value)}
          />
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="eyebrow mb-1 block">
                Filament / material
              </span>
              <select
                className="desk-input w-full"
                value={form.consumablePoolId}
                onChange={(event) =>
                  updateField("consumablePoolId", event.target.value)
                }
              >
                <option value="">No preference</option>
                {groupPoolsByMaterial(poolsQuery.data ?? []).map(([material, pools]) => (
                  <optgroup key={material} label={material}>
                    {pools.map((pool) => (
                      <option key={pool.id} value={pool.id}>
                        {pool.color || "Default color"}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {poolsQuery.isLoading ? (
                <p className="mt-1 text-xs text-muted">Loading filament...</p>
              ) : null}
              {poolsQuery.isError ? (
                <p className="mt-1 text-xs text-danger">
                  {poolsQuery.error.message}
                </p>
              ) : null}
            </label>
            <label className="block">
              <span className="eyebrow mb-1 block">
                Quantity
              </span>
              <input
                className="desk-input w-full font-mono"
                min={1}
                type="number"
                value={form.quantity}
                onChange={(event) =>
                  updateField("quantity", Math.max(1, Number(event.target.value) || 1))
                }
              />
            </label>
            <label className="block">
              <span className="eyebrow mb-1 block">
                Estimated filament (g) &mdash; optional
              </span>
              <input
                className="desk-input w-full font-mono"
                min={0}
                step="0.01"
                type="number"
                value={form.estimatedFilamentGrams}
                onChange={(event) =>
                  updateField("estimatedFilamentGrams", event.target.value)
                }
              />
              <span className="mt-1 block text-xs text-muted">
                If you know it from your slicer &mdash; staff can adjust this.
              </span>
            </label>
            <TextInput label="Source link (optional)" value={form.sourceLink} onChange={(value) => updateField("sourceLink", value)} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <FilePicker
              accept=".stl,.3mf,.step,.stp,.obj,.amf,.ply,.gcode,.gco,.iges,.igs,.dxf"
              files={modelFiles}
              label="Model, CAD, or toolpath files"
              setFiles={setModelFiles}
            />
            <FilePicker
              accept="image/*,application/pdf"
              files={screenshotFiles}
              label="Estimated print-time screenshots (Bambu Lab)"
              setFiles={setScreenshotFiles}
            />
          </div>
        </fieldset>

        {uploadProgress ? <p className="text-sm text-muted">{uploadProgress}</p> : null}
        {submitError ? (
          <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {submitError.message}
          </p>
        ) : null}
        <button
          className="desk-button-primary w-full disabled:cursor-not-allowed disabled:opacity-50"
          disabled={
            !form.title.trim() ||
            submitPending
          }
          type="submit"
        >
          {submitPending ? "Submitting..." : "Submit print request"}
        </button>
      </form>
    </Card>
  );
}
