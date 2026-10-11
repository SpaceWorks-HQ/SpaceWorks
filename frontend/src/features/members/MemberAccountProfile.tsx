import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountKey, editProfile, ownProfile, type AccountProfile } from "./memberAccountApi";

function ProfileForm({ makerspaceId, profile }: { makerspaceId: number; profile: AccountProfile }) {
  const [draft, setDraft] = useState(profile);
  const client = useQueryClient();
  const save = useMutation({ mutationFn: () => editProfile(makerspaceId, draft), onSuccess: () => client.invalidateQueries({ queryKey: ["member"] }) });
  const limits = { display_name: 200, first_name: 150, last_name: 150, phone: 32 };
  const labels = { display_name: "Display name", first_name: "First name", last_name: "Last name", phone: "Contact phone" };
  return <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    {(Object.keys(labels) as (keyof AccountProfile)[]).map((name) => <label key={name} className="text-sm">{labels[name]}<input className="desk-input mt-1" maxLength={limits[name]} value={draft[name]} onChange={(event) => setDraft({ ...draft, [name]: event.target.value })} /></label>)}
    <p className="text-sm text-muted">These contact fields do not change your verified sign-in methods.</p>
    <button className="desk-button-primary" disabled={save.isPending}>Save profile</button>
    {save.error ? <p role="alert" className="text-danger">{save.error.message}</p> : null}
    {save.isSuccess ? <p role="status">Profile saved.</p> : null}
  </form>;
}

export function MemberAccountProfile({ makerspaceId }: { makerspaceId: number }) {
  const profile = useQuery({ queryKey: [...accountKey(makerspaceId), "profile"], queryFn: () => ownProfile(makerspaceId), retry: false });
  return <section className="desk-panel p-5"><h2 className="title-panel mb-4">Your profile</h2>
    {profile.isLoading ? <p role="status">Loading profile…</p> : null}
    {profile.error ? <p role="alert" className="text-danger">{profile.error.message}</p> : null}
    {profile.data ? <ProfileForm key={JSON.stringify(profile.data)} makerspaceId={makerspaceId} profile={profile.data} /> : null}
  </section>;
}
