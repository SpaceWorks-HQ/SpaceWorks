import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import type { MemberProfile } from "./MemberProfilePanel";

type DirectoryEntry = {
  membership_id: number;
  display_name: string;
  headline: string;
  avatar_url: string | null;
};

type Directory = { members: DirectoryEntry[]; hidden_count: number };

const IDENTITY_TONES = [
  { border: "border-accent", surface: "bg-accent/15", ink: "text-accent-ink" },
  { border: "border-secondary", surface: "bg-secondary/15", ink: "text-secondary-ink" },
  { border: "border-success", surface: "bg-success/15", ink: "text-success-ink" },
  { border: "border-warn", surface: "bg-warn/15", ink: "text-warn-ink" },
] as const;

function identityTone(identity: string | number) {
  const text = String(identity);
  const total = [...text].reduce((sum, character) => sum + character.codePointAt(0)!, 0);
  return IDENTITY_TONES[total % IDENTITY_TONES.length];
}

/**
 * Who else is here — but only the people who chose to be listed.
 *
 * The row carries a display name and an avatar and nothing else: the backend does not
 * send contact details on this endpoint at all, because otherwise "see who else is here"
 * is an address harvest available to anyone the space admits.
 */
export function MemberDirectory({ makerspaceId }: { makerspaceId: number }) {
  const [openId, setOpenId] = useState<number | null>(null);
  const directory = useQuery({
    queryKey: ["member", "directory", makerspaceId],
    queryFn: () => staffRequest<Directory>(`/member/makerspaces/${makerspaceId}/directory`),
    retry: false,
  });
  const detail = useQuery({
    queryKey: ["member", "directory", makerspaceId, openId],
    queryFn: () =>
      staffRequest<MemberProfile>(
        `/member/makerspaces/${makerspaceId}/directory/${openId}`,
      ),
    enabled: openId !== null,
    retry: false,
  });

  if (directory.isLoading) {
    return <section className="desk-panel p-5 text-sm text-muted">Loading members…</section>;
  }
  if (directory.isError) return null;

  const entries = directory.data?.members ?? [];
  const hidden = directory.data?.hidden_count ?? 0;

  return (
    <section className="desk-panel p-5">
      <h2 className="title-panel">Members</h2>
      {entries.length === 0 ? (
        <p className="mt-1 text-sm text-muted">Nobody has published a profile yet.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {entries.map((entry) => {
            const tone = identityTone(entry.membership_id);
            return <li className={`border-l-2 ${openId === entry.membership_id ? "border-secondary bg-secondary/15" : tone.border} pl-2`} key={entry.membership_id}>
              <button
                className="desk-button-ghost w-full justify-start text-left"
                type="button"
                onClick={() =>
                  setOpenId(openId === entry.membership_id ? null : entry.membership_id)
                }
                aria-expanded={openId === entry.membership_id}
              >
                <span className={`h-10 w-10 shrink-0 overflow-hidden rounded-full border ${tone.border} ${tone.surface}`}>
                  {entry.avatar_url ? (
                    <img src={entry.avatar_url} alt="" className="h-full w-full object-cover" />
                  ) : null}
                </span>
                <span className="min-w-0">
                  <span className="block font-medium text-ink">{entry.display_name}</span>
                  {entry.headline ? (
                    <span className="block truncate text-sm text-muted">{entry.headline}</span>
                  ) : null}
                </span>
              </button>
              {/* Unmounted rather than hidden when collapsed, so keyboard users cannot
                  tab into links they cannot see. */}
              {openId === entry.membership_id && detail.data ? (
                <ProfileDetail profile={detail.data} />
              ) : null}
            </li>;
          })}
        </ul>
      )}
      {hidden > 0 ? (
        <p className="mt-3 text-sm text-muted">
          {`${hidden} more ${hidden === 1 ? "member has" : "members have"} not published a profile.`}
        </p>
      ) : null}
    </section>
  );
}

function ProfileDetail({ profile }: { profile: MemberProfile }) {
  return (
    <div className="mt-2 rounded-lg border border-secondary bg-secondary/10 p-3">
      {profile.institution ? (
        <p className="text-sm text-muted">{profile.institution}</p>
      ) : null}
      {profile.bio ? <p className="mt-2 text-sm text-ink">{profile.bio}</p> : null}
      <TagRow label="Interests" values={profile.interests} />
      <TagRow label="Languages" values={profile.languages} />
      {profile.education.length ? (
        <ul className="mt-3 space-y-2 text-sm text-muted">
          {profile.education.map((row, index) => {
            const tone = identityTone([row.qualification, row.institution, row.year].join("|"));
            return <li className={`border-l-2 ${tone.border} pl-3`} key={index}>
              {[row.qualification, row.institution, row.year].filter(Boolean).join(" · ")}
            </li>;
          })}
        </ul>
      ) : null}
      {profile.github_contributions !== null ? (
        <p className="mt-3 text-sm text-muted">
          <span className="font-mono">{profile.github_contributions}</span> GitHub contributions in the last year.
        </p>
      ) : null}
      {typeof profile.activity?.events_attended === "number" ? (
        <p className="mt-1 text-sm text-muted">
          <span className="font-mono">{profile.activity.events_attended}</span> events attended here.
        </p>
      ) : null}
      {profile.activity?.recent_attended_events?.length ? (
        <div className="mt-3">
          {/* "Recent" is load-bearing, not decoration: the backend caps this list, so a
              heading reading "Events attended" would claim to be the full history. The
              count above is the truthful total. */}
          <h3 className="title-section">Recently attended</h3>
          <ul className="mt-1 space-y-1 text-sm text-muted">
            {profile.activity.recent_attended_events.map((event) => (
              <li key={event.id}>
                {event.title} ·{" "}
                <span className="font-mono">{new Date(event.starts_at).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {profile.projects.length ? (
        <div className="mt-3 space-y-3">
          {profile.projects.map((project) => {
            const tone = identityTone(project.id);
            return <article key={project.id} className={`rounded-lg border ${tone.border} ${tone.surface} p-3`}>
              {project.image_url ? (
                <img
                  src={project.image_url}
                  alt=""
                  className="mb-2 max-h-40 w-full rounded-md object-cover"
                />
              ) : null}
              <h3 className="title-section">{project.title}</h3>
              {project.description ? (
                <p className="mt-1 text-sm text-muted">{project.description}</p>
              ) : null}
              {project.links.length ? (
                <ul className="mt-2 flex flex-wrap gap-3 text-sm">
                  {project.links.map((link, index) => {
                    const linkTone = identityTone(`${link.label}|${link.url}`);
                    return <li key={index}>
                      {/* External and member-authored: noopener/noreferrer keeps the
                          destination from reaching back through window.opener. */}
                      <a
                        className={`${linkTone.ink} underline`}
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {link.label}
                      </a>
                    </li>;
                  })}
                </ul>
              ) : null}
            </article>;
          })}
        </div>
      ) : null}
    </div>
  );
}

function TagRow({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <p className="mt-2 text-sm text-muted">
      <span className="eyebrow text-ink">{label}:</span> {values.join(", ")}
    </p>
  );
}
