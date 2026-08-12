import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { ImageUploader } from "../staff/ImageUploader";

export type MemberProject = {
  id: number;
  title: string;
  description: string;
  links: { label: string; url: string }[];
  image_url: string | null;
};

export interface MemberProfileActivity {
  events_attended?: number;
  events_registered?: number;
  recent_attended_events?: { id: number; title: string; starts_at: string }[];
}

export type MemberProfile = {
  membership_id: number;
  display_name: string;
  is_visible: boolean;
  show_attended_events: boolean;
  headline: string;
  institution: string;
  bio: string;
  avatar_url: string | null;
  interests: string[];
  languages: string[];
  education: { institution: string; qualification?: string; year?: string }[];
  github_username: string;
  github_contributions: number | null;
  projects: MemberProject[];
  activity: MemberProfileActivity;
};

type ProjectDraft = {
  id?: number;
  title: string;
  description: string;
  links: { label: string; url: string }[];
};

const tagsToText = (values: string[]) => values.join(", ");
const textToTags = (value: string) =>
  value.split(",").map((item) => item.trim()).filter(Boolean);

const PROFILE_TONES = [
  "border-accent bg-accent/15",
  "border-secondary bg-secondary/15",
  "border-success bg-success/15",
  "border-warn bg-warn/15",
] as const;

function profileToneForIdentity(identity: string | number | undefined) {
  if (identity === undefined || identity === "") return "border-secondary bg-secondary/15";
  const total = [...String(identity)].reduce((sum, character) => sum + character.codePointAt(0)!, 0);
  return PROFILE_TONES[total % PROFILE_TONES.length];
}

/**
 * The member's own profile: what they choose to show the rest of their makerspace.
 *
 * Editing is a single form that PUTs the whole thing, projects included — the API
 * replaces the project list rather than merging it, because with a merge there is no
 * way to express deleting one.
 */
export function MemberProfilePanel({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const profile = useQuery({
    queryKey: ["member", "profile-page", makerspaceId],
    queryFn: () => staffRequest<MemberProfile>(`/member/makerspaces/${makerspaceId}/profile`),
    retry: false,
  });
  const [draft, setDraft] = useState<MemberProfile | null>(null);
  const [interests, setInterests] = useState("");
  const [languages, setLanguages] = useState("");
  const [projects, setProjects] = useState<ProjectDraft[]>([]);
  // Set by any edit, cleared by a successful save. Guards the re-seed effect below.
  const [dirty, setDirty] = useState(false);

  // Seed once, then only re-seed when the form has no unsaved edits.
  //
  // An image upload invalidates this query, so a naive "re-seed on every snapshot" reset
  // every field to the last saved copy — a member who wrote a bio and then changed their
  // avatar lost the bio with no warning. Image URLs are the one thing that must still
  // refresh after an upload, so they are merged in separately below.
  useEffect(() => {
    if (!profile.data || dirty) return;
    setDraft(profile.data);
    setInterests(tagsToText(profile.data.interests));
    setLanguages(tagsToText(profile.data.languages));
    setProjects(profile.data.projects.map((project) => ({ ...project })));
  }, [profile.data, dirty]);

  useEffect(() => {
    if (!profile.data || !dirty) return;
    // Dirty form: keep every edited field, but take the new image URLs, since those
    // changed on the server and are not editable here.
    const server = profile.data;
    setDraft((current) => (current ? { ...current, avatar_url: server.avatar_url, projects: server.projects } : current));
  }, [profile.data, dirty]);

  const save = useMutation({
    mutationFn: () =>
      staffRequest<MemberProfile>(`/member/makerspaces/${makerspaceId}/profile`, {
        method: "PUT",
        body: JSON.stringify({
          is_visible: draft?.is_visible ?? false,
          show_attended_events: draft?.show_attended_events ?? false,
          headline: draft?.headline ?? "",
          institution: draft?.institution ?? "",
          bio: draft?.bio ?? "",
          github_username: draft?.github_username ?? "",
          interests: textToTags(interests),
          languages: textToTags(languages),
          education: draft?.education ?? [],
          projects: projects
            .filter((project) => project.title.trim())
            .map((project) => ({
              ...(project.id ? { id: project.id } : {}),
              title: project.title.trim(),
              description: project.description,
              links: project.links.filter((link) => link.label.trim() && link.url.trim()),
            })),
        }),
      }),
    onSuccess: () => {
      setDirty(false);
      return client.invalidateQueries({ queryKey: ["member", "profile-page", makerspaceId] });
    },
  });

  if (profile.isLoading) {
    return <section className="desk-panel p-5 text-sm text-muted">Loading your profile…</section>;
  }
  if (!draft) return null;

  const patch = (changes: Partial<MemberProfile>) => {
    setDirty(true);
    setDraft({ ...draft, ...changes });
  };
  const editProjects = (next: ProjectDraft[]) => {
    setDirty(true);
    setProjects(next);
  };

  return (
    <section className="desk-panel p-5">
      <h2 className="title-panel">Your maker profile</h2>
      <p className="mt-1 text-sm text-muted">
        Nothing here is shown to other members until you publish it.
      </p>

      <label className="mt-4 flex items-center gap-2 text-sm text-ink">
        <input
          type="checkbox"
          className="h-4 w-4"
          checked={draft.is_visible}
          onChange={(event) => patch({ is_visible: event.target.checked })}
        />
        Show my profile in this makerspace&apos;s member directory
      </label>
      <label className="mt-2 flex items-center gap-2 text-sm text-ink">
        <input
          type="checkbox"
          className="h-4 w-4"
          checked={draft.show_attended_events}
          onChange={(event) => patch({ show_attended_events: event.target.checked })}
        />
        Also show the events I have attended on my profile
      </label>

      <div className="mt-4">
        <ImageUploader
          endpoint={`/member/makerspaces/${makerspaceId}/profile/image`}
          currentUrl={draft.avatar_url}
          label="Avatar"
          onChanged={() =>
            client.invalidateQueries({ queryKey: ["member", "profile-page", makerspaceId] })
          }
        />
      </div>

      <Field id="profile-headline" label="Headline">
        <input
          id="profile-headline"
          className="desk-input mt-1 w-full"
          value={draft.headline}
          onChange={(event) => patch({ headline: event.target.value })}
        />
      </Field>
      <Field id="profile-institution" label="Institution">
        <input
          id="profile-institution"
          className="desk-input mt-1 w-full"
          value={draft.institution}
          onChange={(event) => patch({ institution: event.target.value })}
        />
      </Field>
      <Field id="profile-bio" label="Bio">
        <textarea
          id="profile-bio"
          className="desk-input mt-1 w-full"
          rows={4}
          value={draft.bio}
          onChange={(event) => patch({ bio: event.target.value })}
        />
      </Field>
      <Field id="profile-interests" label="Interests" hint="Comma separated">
        <input
          id="profile-interests"
          className="desk-input mt-1 w-full"
          value={interests}
          onChange={(event) => { setDirty(true); setInterests(event.target.value); }}
        />
      </Field>
      <Field id="profile-languages" label="Languages" hint="Comma separated">
        <input
          id="profile-languages"
          className="desk-input mt-1 w-full"
          value={languages}
          onChange={(event) => { setDirty(true); setLanguages(event.target.value); }}
        />
      </Field>
      <Field id="profile-github" label="GitHub username">
        <input
          id="profile-github"
          className="desk-input mt-1 w-full"
          value={draft.github_username}
          onChange={(event) => patch({ github_username: event.target.value })}
        />
      </Field>
      {draft.github_contributions !== null ? (
        <p className="mt-1 text-sm text-muted">
          <span className="font-mono">{draft.github_contributions}</span> contributions in the last year.
        </p>
      ) : null}

      <h3 className="title-section mt-6">Projects</h3>
      <div className="mt-2 space-y-3">
        {projects.map((project, index) => (
          <ProjectEditor
            key={project.id ?? `new-${index}`}
            makerspaceId={makerspaceId}
            project={project}
            imageUrl={
              draft.projects.find((row) => row.id === project.id)?.image_url ?? null
            }
            onChange={(next) =>
              editProjects(projects.map((row, position) => (position === index ? next : row)))
            }
            onRemove={() =>
              editProjects(projects.filter((_, position) => position !== index))
            }
            onImageChanged={() =>
              client.invalidateQueries({ queryKey: ["member", "profile-page", makerspaceId] })
            }
          />
        ))}
      </div>
      <button
        className="desk-button-ghost mt-3"
        type="button"
        onClick={() =>
          editProjects([...projects, { title: "", description: "", links: [] }])
        }
      >
        Add a project
      </button>

      {save.error ? (
        <p className="mt-3 text-sm text-danger" role="alert">
          {save.error instanceof Error ? save.error.message : "Could not save."}
        </p>
      ) : null}
      <button
        className="desk-button-secondary mt-4"
        type="button"
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        {save.isPending ? "Saving…" : "Save profile"}
      </button>
    </section>
  );
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-3">
      <label className="eyebrow block" htmlFor={id}>
        {label}
        {hint ? <span className="ml-2 normal-case tracking-normal text-muted">{hint}</span> : null}
      </label>
      {children}
    </div>
  );
}

function ProjectEditor({
  makerspaceId,
  project,
  imageUrl,
  onChange,
  onRemove,
  onImageChanged,
}: {
  makerspaceId: number;
  project: ProjectDraft;
  imageUrl: string | null;
  onChange: (next: ProjectDraft) => void;
  onRemove: () => void;
  onImageChanged: () => void;
}) {
  return (
    <div className={`rounded-lg border ${profileToneForIdentity(project.id)} p-3`}>
      <input
        className="desk-input w-full"
        placeholder="Project title"
        aria-label="Project title"
        value={project.title}
        onChange={(event) => onChange({ ...project, title: event.target.value })}
      />
      <textarea
        className="desk-input mt-2 w-full"
        rows={2}
        placeholder="What is it?"
        aria-label="Project description"
        value={project.description}
        onChange={(event) => onChange({ ...project, description: event.target.value })}
      />
      {/* An image can only be attached to a project that exists server-side — a new one
          has no id to attach it to, so it appears after the first save. */}
      {project.id ? (
        <div className="mt-3">
          <ImageUploader
            endpoint={`/member/makerspaces/${makerspaceId}/profile/image`}
            currentUrl={imageUrl}
            label="Project image"
            extraBody={{ project_id: project.id }}
            clearQuery={`?project_id=${project.id}`}
            onChanged={onImageChanged}
          />
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted">Save the project to add an image.</p>
      )}
      <div className="mt-2 space-y-2">
        {project.links.map((link, index) => (
          <div key={index} className={`flex flex-col gap-2 border-l-2 ${profileToneForIdentity(`${link.label}|${link.url}`)} p-2 sm:flex-row`}>
            <input
              className="desk-input w-full sm:w-40"
              placeholder="Label"
              aria-label="Link label"
              value={link.label}
              onChange={(event) =>
                onChange({
                  ...project,
                  links: project.links.map((row, position) =>
                    position === index ? { ...row, label: event.target.value } : row,
                  ),
                })
              }
            />
            <input
              className="desk-input w-full"
              placeholder="https://…"
              aria-label="Link URL"
              value={link.url}
              onChange={(event) =>
                onChange({
                  ...project,
                  links: project.links.map((row, position) =>
                    position === index ? { ...row, url: event.target.value } : row,
                  ),
                })
              }
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-2">
        <button
          className="desk-button-ghost"
          type="button"
          onClick={() =>
            onChange({ ...project, links: [...project.links, { label: "", url: "" }] })
          }
        >
          Add link
        </button>
        <button className="desk-button-danger" type="button" onClick={onRemove}>
          Remove project
        </button>
      </div>
    </div>
  );
}
