import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Field } from "../../components/ui";
import { SpacePackProfilePicker } from "./SpacePackProfilePicker";
import { exportSpacePack, importSpacePack, savePackProfile, type PackPreview, type SpacePack } from "./spacePacksApi";

export function SpacePacksPanel({ makerspaceId, isSuperadmin }: { makerspaceId: number; isSuperadmin: boolean }) {
  const queries = useQueryClient();
  const [source, setSource] = useState("");
  const [preview, setPreview] = useState<PackPreview | null>(null);
  const [profileName, setProfileName] = useState("");
  const [profileId, setProfileId] = useState<number | "">("");
  const [message, setMessage] = useState("");
  const [inputError, setInputError] = useState("");
  const setPack = (text: string) => { setSource(text); setPreview(null); setMessage(""); setInputError(""); };
  const parse = (): SpacePack => {
    try { return JSON.parse(source) as SpacePack; }
    catch { throw new Error("Enter valid JSON or export a pack first."); }
  };
  const exportPack = useMutation({ mutationFn: () => exportSpacePack(makerspaceId),
    onSuccess: (pack) => setPack(JSON.stringify(pack, null, 2)) });
  const previewPack = useMutation({ mutationFn: () => importSpacePack(makerspaceId, parse()),
    onSuccess: (result) => { setPreview(result); setMessage("Preview ready. No configuration changed."); } });
  const applyPack = useMutation({
    mutationFn: () => importSpacePack(makerspaceId, parse(), preview?.base_checksum),
    onSuccess: () => {
      setPreview(null); setMessage("Pack applied.");
      // A pack can affect multiple domain caches. Refresh all active server-state
      // queries once rather than maintaining a second list of every settings key.
      void queries.invalidateQueries();
    },
    onError: () => setPreview(null),
  });
  const saveProfile = useMutation({ mutationFn: () => savePackProfile(profileName.trim(), parse()),
    onSuccess: () => { setMessage("Install profile saved."); void queries.invalidateQueries({ queryKey: ["space-pack-profiles"] }); } });
  const pending = exportPack.isPending || previewPack.isPending || applyPack.isPending || saveProfile.isPending;
  const error = inputError || exportPack.error?.message || previewPack.error?.message || applyPack.error?.message || saveProfile.error?.message;
  return <section className="grid min-w-0 gap-3 rounded-md border border-line bg-bg p-4" aria-label="Space packs">
    <h3 className="text-base font-semibold text-ink">Space packs</h3>
    <p className="text-sm text-muted">Copy configuration between spaces. Packs contain policies, roles, templates and catalogue definitions. Item templates start with zero stock. Review template text before sharing a pack.</p>
    <button type="button" className="desk-button justify-self-start" disabled={pending} onClick={() => exportPack.mutate()}>Export configuration</button>
    <Field label="Space pack JSON">
      <textarea className="desk-input min-h-48 w-full font-mono text-xs" value={source} disabled={pending}
        onChange={(event) => setPack(event.target.value)} />
    </Field>
    <div className="flex flex-wrap gap-2">
      <button type="button" className="desk-button" disabled={pending || !source.trim()} onClick={() => { setPreview(null); previewPack.mutate(); }}>Preview import</button>
      <button type="button" className="desk-button-primary" disabled={pending || !preview || !preview.changes.length} onClick={() => applyPack.mutate()}>Apply reviewed pack</button>
      <button type="button" className="desk-button" disabled={pending || !source.trim()} onClick={() => {
        try {
          const url = URL.createObjectURL(new Blob([JSON.stringify(parse(), null, 2)], { type: "application/json" }));
          const anchor = document.createElement("a"); anchor.href = url; anchor.download = "space-pack.json"; anchor.click(); URL.revokeObjectURL(url);
        } catch (failure) { setInputError((failure as Error).message); }
      }}>Download JSON</button>
    </div>
    {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
    {message ? <p role="status" className="text-sm text-ink">{message}</p> : null}
    {preview ? <div className="grid gap-2">
      <p className="text-sm">{preview.changes.length} changes. Entries absent from the pack are retained.</p>
      {preview.changes.map((change) => <details key={`${change.section}/${change.key}`} className="min-w-0 text-sm">
        <summary>{change.section}: {change.key}</summary>
        <div className="grid gap-2 sm:grid-cols-2">
          <pre className="overflow-auto whitespace-pre-wrap break-all rounded border border-line p-2">Before: {JSON.stringify(change.before, null, 2)}</pre>
          <pre className="overflow-auto whitespace-pre-wrap break-all rounded border border-line p-2">After: {JSON.stringify(change.after, null, 2)}</pre>
        </div>
      </details>)}
    </div> : null}
    {isSuperadmin ? <div className="grid gap-3 border-t border-line pt-3">
      <SpacePackProfilePicker value={profileId} disabled={pending} onChange={(profile) => {
        setProfileId(profile?.id ?? ""); if (profile) setPack(JSON.stringify(profile.pack, null, 2));
      }} />
      <Field label="New install profile name"><input className="desk-input w-full" value={profileName} maxLength={120}
        disabled={pending} onChange={(event) => setProfileName(event.target.value)} /></Field>
      <button type="button" className="desk-button justify-self-start" disabled={pending || !profileName.trim() || !source.trim()}
        onClick={() => saveProfile.mutate()}>Save platform profile</button>
    </div> : null}
  </section>;
}
