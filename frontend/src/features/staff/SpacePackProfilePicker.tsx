import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Field } from "../../components/ui";
import { listPackProfiles, type PackProfile } from "./spacePacksApi";

export function SpacePackProfilePicker({ value, onChange, disabled = false, enabled = true }: {
  value: number | ""; onChange: (profile: PackProfile | null) => void; disabled?: boolean; enabled?: boolean;
}) {
  const [page, setPage] = useState(1);
  const profiles = useQuery({ queryKey: ["space-pack-profiles", page], queryFn: () => listPackProfiles(page), enabled });
  return <div className="grid gap-2">
    <Field label="Saved install profile">
      <select className="desk-input w-full" value={value} disabled={disabled || profiles.isLoading}
        onChange={(event) => onChange(profiles.data?.results.find((profile) => profile.id === Number(event.target.value)) ?? null)}>
        <option value="">No saved profile</option>
        {(profiles.data?.results ?? []).map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
      </select>
    </Field>
    {profiles.error ? <p role="alert" className="text-sm text-danger">{profiles.error.message}</p> : null}
    {(profiles.data?.count ?? 0) > 24 ? <div className="flex gap-2">
      <button type="button" className="desk-button" disabled={disabled || page === 1}
        onClick={() => { onChange(null); setPage(page - 1); }}>Previous profiles</button>
      <button type="button" className="desk-button" disabled={disabled || !profiles.data?.next}
        onClick={() => { onChange(null); setPage(page + 1); }}>Next profiles</button>
    </div> : null}
  </div>;
}
