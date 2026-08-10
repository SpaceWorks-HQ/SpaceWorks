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
      <h2 className="font-semibold text-ink">Members</h2>
      {entries.length === 0 ? (
        <p className="mt-1 text-sm text-muted">Nobody has published a profile yet.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {entries.map((entry) => (
            <li key={entry.membership_id}>
              <button
                className="flex w-full items-center gap-3 rounded-lg border border-line p-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                type="button"
                onClick={() =>
                  setOpenId(openId === entry.membership_id ? null : entry.membership_id)
                }
                aria-expanded={openId === entry.membership_id}
              >
                <span className="h-10 w-10 shrink-0 overflow-hidden rounded-full border border-line bg-surface">
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
            </li>
          ))}
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
    <div className="mt-2 rounded-lg border border-line bg-surface p-3">
      {profile.institution ? (
        <p className="text-sm text-muted">{profile.institution}</p>
      ) : null}
      {profile.bio ? <p className="mt-2 text-sm text-ink">{profile.bio}</p> : null}
      <TagRow label="Interests" values={profile.interests} />
      <TagRow label="Languages" values={profile.languages} />
      {profile.education.length ? (
        <ul className="mt-3 space-y-1 text-sm text-muted">
          {profile.education.map((row, index) => (
            <li key={index}>
              {[row.qualification, row.institution, row.year].filter(Boolean).join(" · ")}
            </li>
          ))}
        </ul>
      ) : null}
      {profile.github_contributions !== null ? (
        <p className="mt-3 text-sm text-muted">
          {profile.github_contributions} GitHub contributions in the last year.
        </p>
      ) : null}
      {typeof profile.activity?.events_attended === "number" ? (
        <p className="mt-1 text-sm text-muted">
          {profile.activity.events_attended} events attended here.
        </p>
      ) : null}
      {profile.activity?.recent_attended_events?.length ? (
        <div className="mt-3">
          {/* "Recent" is load-bearing, not decoration: the backend caps this list, so a
              heading reading "Events attended" would claim to be the full history. The
              count above is the truthful total. */}
          <h4 className="text-sm font-medium text-ink">Recently attended</h4>
          <ul className="mt-1 space-y-1 text-sm text-muted">
            {profile.activity.recent_attended_events.map((event) => (
              <li key={event.id}>
                {event.title} ·{" "}
                {new Date(event.starts_at).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {profile.projects.length ? (
        <div className="mt-3 space-y-3">
          {profile.projects.map((project) => (
            <article key={project.id} className="rounded-lg border border-line bg-panel p-3">
              {project.image_url ? (
                <img
                  src={project.image_url}
                  alt=""
                  className="mb-2 max-h-40 w-full rounded-md object-cover"
                />
              ) : null}
              <h4 className="font-medium text-ink">{project.title}</h4>
              {project.description ? (
                <p className="mt-1 text-sm text-muted">{project.description}</p>
              ) : null}
              {project.links.length ? (
                <ul className="mt-2 flex flex-wrap gap-3 text-sm">
                  {project.links.map((link, index) => (
                    <li key={index}>
                      {/* External and member-authored: noopener/noreferrer keeps the
                          destination from reaching back through window.opener. */}
                      <a
                        className="text-accent-ink underline"
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TagRow({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <p className="mt-2 text-sm text-muted">
      <span className="font-medium text-ink">{label}:</span> {values.join(", ")}
    </p>
  );
}
