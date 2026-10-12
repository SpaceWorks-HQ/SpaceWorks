import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";
import { BRAND_SURFACES, brandContrastReport, brandPaletteStyle, deriveBrandPalette } from "../../lib/brandColours";
import type { Makerspace } from "./StaffPanels";

type Props = { makerspace: Makerspace; settings?: Makerspace; loading: boolean };

export function MakerspaceThemeSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const saved = settings?.theme_config ?? {};
  const savedPrimary = typeof saved.primary_color === "string" ? saved.primary_color : "";
  const savedAccent = typeof saved.accent_color === "string" ? saved.accent_color : "";
  const [primary, setPrimary] = useState(savedPrimary);
  const [accent, setAccent] = useState(savedAccent);
  useEffect(() => {
    setPrimary(savedPrimary);
    setAccent(savedAccent);
  }, [makerspace.id, savedPrimary, savedAccent]);
  const theme = { ...saved, primary_color: primary.trim(), accent_color: accent.trim() };
  const report = brandContrastReport(theme);
  const changed = theme.primary_color !== (saved.primary_color ?? "") || theme.accent_color !== (saved.accent_color ?? "");
  const save = useMutation({
    mutationFn: (input: { id: number; slug: string; theme: Record<string, string> }) => staffRequest<Makerspace>(`/admin/makerspaces/${input.id}`, {
      method: "PATCH", body: JSON.stringify({ theme_config: input.theme }),
    }),
    onSuccess: (_result, input) => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", input.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["tenant-bootstrap", input.slug] });
      queryClient.invalidateQueries({ queryKey: ["member"] });
      queryClient.invalidateQueries({ queryKey: ["runtime-tenant"] });
      queryClient.invalidateQueries({ queryKey: ["runtime-tenant-origin"] });
    },
  });
  useEffect(() => { save.reset(); }, [makerspace.id]);
  return <form className="mt-6 space-y-3" onSubmit={(event) => {
    event.preventDefault();
    if (settings && report.valid && changed && !loading && !save.isPending) save.mutate({ id: makerspace.id, slug: makerspace.slug, theme });
  }}>
    <h4 className="title-section">Public and member colours</h4>
    <p className="text-sm text-muted">Leave blank for the product palette. Button text is chosen automatically; link colours adapt to light and dark mode. The staff console keeps the product theme.</p>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm" htmlFor="theme-primary">Primary fill
        <input id="theme-primary" className="desk-input" placeholder="#f9a8d4" value={primary} disabled={loading || save.isPending} onChange={(event) => setPrimary(event.target.value)} />
      </label>
      <label className="grid gap-1 text-sm" htmlFor="theme-accent">Link colour seed
        <input id="theme-accent" className="desk-input" placeholder="Derived from primary" value={accent} disabled={loading || save.isPending} onChange={(event) => setAccent(event.target.value)} />
      </label>
    </div>
    <div className="grid gap-3 sm:grid-cols-2">
      {(["light", "dark"] as const).map((mode) => {
        const palette = deriveBrandPalette(theme, mode);
        const preview = report.valid ? palette : deriveBrandPalette({}, mode);
        const style = brandPaletteStyle(preview);
        const worstText = Math.min(...palette.pairs.filter((pair) => pair.minimum === 4.5).map((pair) => pair.ratio));
        const worstUI = Math.min(...palette.pairs.filter((pair) => pair.minimum === 3).map((pair) => pair.ratio));
        const surface = BRAND_SURFACES[mode][0].join(" ");
        return <div key={mode} data-testid={`theme-preview-${mode}`} style={{ ...style, backgroundColor: `rgb(${surface})`, color: mode === "dark" ? "white" : "black" }} className="rounded-lg border border-line p-3">
          <p className="font-semibold">{mode === "light" ? "Light" : "Dark"} preview</p>
          {!report.valid ? <p className="text-xs">Product palette fallback shown; ratios below describe the entered colours.</p> : null}
          <p className="my-2 text-sm" style={{ color: `rgb(${preview.ink.join(" ")})` }}>Derived link colour: rgb({preview.ink.join(", ")})</p>
          <button className="desk-button-secondary" type="button">Example action</button>
          <p className="mt-2 text-xs">Text minimum {worstText.toFixed(2)}:1 (AA 4.5:1); component minimum {worstUI.toFixed(2)}:1 (AA 3:1).</p>
        </div>;
      })}
    </div>
    <div aria-live="polite">
      {report.errors.map((error) => <p className="text-sm text-danger" key={error}>{error}</p>)}
      {report.failures.map((pair) => <p className="text-sm text-danger" key={`${pair.mode}-${pair.pair}`}>{pair.mode}: {pair.pair} is {pair.ratio.toFixed(2)}:1; requires {pair.minimum}:1.</p>)}
      {report.valid ? <p className="text-sm text-success-ink">All checked pairs meet WCAG AA in both modes.</p> : <p className="text-sm text-danger">Choose a lighter or darker primary fill. Public pages use the product palette until a valid palette is saved.</p>}
      {save.error ? <p className="text-sm text-danger">{save.error.message}</p> : null}
      {save.isSuccess && !changed ? <p className="text-sm text-success-ink">Colours saved.</p> : null}
    </div>
    <button type="submit" className="desk-button-primary" disabled={!settings || loading || save.isPending || !changed || !report.valid}>{save.isPending ? "Saving..." : "Save colours"}</button>
  </form>;
}
