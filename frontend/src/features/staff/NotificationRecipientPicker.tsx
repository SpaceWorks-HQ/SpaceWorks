import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { ScopePicker, useScopeOptions } from "./NotificationDestinations";
import {
  type DestinationScope,
  type RecipientKind,
  type RecipientRule,
  type RecipientRulesResponse,
  EMPTY_SCOPE,
} from "./notificationDestinationTypes";

const FEATURE_LABELS: Record<string, string> = {
  events: "Events",
  bookings: "Bookings",
  maintenance: "Maintenance",
  members: "Members",
};

const RECIPIENTS_KEY = (makerspaceId: number) =>
  ["notification-recipient-rules", makerspaceId] as const;

type Draft = {
  kind: RecipientKind;
  role_id: number | null;
  user_id: number | null;
  scope: DestinationScope;
};

/**
 * Who hears about one lifecycle event.
 *
 * **An empty selection is not "nobody".** With no rows the alert goes to everyone holding
 * the feature's action, exactly as it did before this picker existed — which is what keeps
 * a space's booking mail flowing when nobody has configured anything. Removing every
 * recipient restores that default rather than silencing the event.
 */
export function NotificationRecipientPicker({ makerspaceId }: { makerspaceId: number }) {
  const path = `/admin/makerspace/${makerspaceId}/notification-recipient-rules`;
  const data = useQuery({
    queryKey: RECIPIENTS_KEY(makerspaceId),
    queryFn: () => staffRequest<RecipientRulesResponse>(path),
  });
  const [selected, setSelected] = useState<{ feature: string; event: string } | null>(null);
  const options = useScopeOptions(makerspaceId);

  const features = data.data?.features ?? [];
  const current = selected ?? (features[0] ? { feature: features[0].key, event: features[0].events[0] } : null);
  const events = features.find((item) => item.key === current?.feature)?.events ?? [];

  return (
    <section aria-labelledby="notification-recipients-heading" className="mt-6">
      <h4 id="notification-recipients-heading" className="text-sm font-semibold text-ink">
        Who gets notified
      </h4>
      <p className="mt-2 text-sm text-muted">
        Pick recipients per event. Leave an event empty to notify everyone whose role
        covers it, which is the default. A member who has turned notifications off is never
        mailed, even when selected.
      </p>

      {data.isLoading ? <p className="mt-3 text-sm text-muted">Loading…</p> : null}
      {!data.isLoading && features.length === 0 ? (
        <p className="mt-3 text-sm text-muted">
          None of the modules with selectable recipients are installed.
        </p>
      ) : null}

      {current ? (
        <>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <label className="grid gap-1 text-sm">
              <span className="text-muted">Area</span>
              <select
                className="desk-input"
                onChange={(event) => {
                  const feature = event.target.value;
                  const first = features.find((item) => item.key === feature)?.events[0] ?? "";
                  setSelected({ feature, event: first });
                }}
                value={current.feature}
              >
                {features.map((feature) => (
                  <option key={feature.key} value={feature.key}>
                    {FEATURE_LABELS[feature.key] ?? feature.key}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm">
              <span className="text-muted">Event</span>
              <select
                className="desk-input"
                onChange={(event) =>
                  setSelected({ feature: current.feature, event: event.target.value })
                }
                value={current.event}
              >
                {events.map((event) => (
                  <option key={event} value={event}>
                    {event.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {data.data ? (
            <EventRecipients
              data={data.data}
              event={current.event}
              feature={current.feature}
              makerspaceId={makerspaceId}
              options={options}
              path={path}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function EventRecipients({
  data,
  event,
  feature,
  makerspaceId,
  options,
  path,
}: {
  data: RecipientRulesResponse;
  event: string;
  feature: string;
  makerspaceId: number;
  options: ReturnType<typeof useScopeOptions>;
  path: string;
}) {
  const queryClient = useQueryClient();
  const saved = useMemo(
    () => data.rules.filter((rule) => rule.feature === feature && rule.event === event),
    [data.rules, event, feature],
  );
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [error, setError] = useState("");
  const rules = drafts ?? saved.map(toDraft);

  const save = useMutation({
    mutationFn: (next: Draft[]) =>
      staffRequest<RecipientRulesResponse>(path, {
        method: "PUT",
        body: JSON.stringify({ feature, event, rules: next }),
      }),
    onSuccess: () => {
      setDrafts(null);
      queryClient.invalidateQueries({ queryKey: RECIPIENTS_KEY(makerspaceId) });
    },
    onError: (err: unknown) =>
      setError(err instanceof Error ? err.message : "Could not save recipients."),
  });

  const update = (next: Draft[]) => {
    setDrafts(next);
    setError("");
  };

  return (
    <div className="mt-3 grid gap-2 rounded-md border border-line bg-bg p-3">
      {rules.length === 0 ? (
        <p className="text-sm text-muted">
          Nobody selected — everyone whose role covers {FEATURE_LABELS[feature] ?? feature}{" "}
          is notified.
        </p>
      ) : null}

      {rules.map((rule, index) => (
        <div className="grid gap-2 border-b border-line pb-2 last:border-0" key={index}>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="desk-input"
              onChange={(changed) =>
                update(
                  rules.map((item, position) =>
                    position === index
                      ? {
                          ...item,
                          kind: changed.target.value as RecipientKind,
                          role_id: null,
                          user_id: null,
                        }
                      : item,
                  ),
                )
              }
              value={rule.kind}
            >
              <option value="role">A role</option>
              <option value="user">A named member</option>
              <option value="members">All members</option>
              <option value="requester">The person it is about</option>
            </select>

            {rule.kind === "role" ? (
              <select
                className="desk-input"
                onChange={(changed) =>
                  update(
                    rules.map((item, position) =>
                      position === index
                        ? { ...item, role_id: Number(changed.target.value) }
                        : item,
                    ),
                  )
                }
                value={rule.role_id ?? ""}
              >
                <option value="">Choose a role…</option>
                {data.roles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
            ) : null}

            {rule.kind === "user" ? (
              <select
                className="desk-input"
                onChange={(changed) =>
                  update(
                    rules.map((item, position) =>
                      position === index
                        ? { ...item, user_id: Number(changed.target.value) }
                        : item,
                    ),
                  )
                }
                value={rule.user_id ?? ""}
              >
                {/* Members of this makerspace only — an outside account cannot be sent
                    notification bodies that carry other people's contact details. */}
                <option value="">Choose a member…</option>
                {data.members.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.username}
                  </option>
                ))}
              </select>
            ) : null}

            <button
              className="desk-btn ml-auto"
              onClick={() => update(rules.filter((_, position) => position !== index))}
              type="button"
            >
              Remove
            </button>
          </div>

          <ScopePicker
            onChange={(scope) =>
              update(
                rules.map((item, position) => (position === index ? { ...item, scope } : item)),
              )
            }
            options={options}
            scope={rule.scope}
          />
        </div>
      ))}

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="flex flex-wrap gap-2">
        <button
          className="desk-btn"
          onClick={() =>
            update([...rules, { kind: "role", role_id: null, user_id: null, scope: EMPTY_SCOPE }])
          }
          type="button"
        >
          Add recipient
        </button>
        <button
          className="desk-btn"
          disabled={save.isPending || drafts === null}
          onClick={() => save.mutate(rules)}
          type="button"
        >
          {save.isPending ? "Saving…" : "Save recipients"}
        </button>
        {drafts !== null ? (
          <button className="desk-btn" onClick={() => setDrafts(null)} type="button">
            Discard changes
          </button>
        ) : null}
      </div>
    </div>
  );
}

function toDraft(rule: RecipientRule): Draft {
  return {
    kind: rule.kind,
    role_id: rule.role_id,
    user_id: rule.user_id,
    scope: rule.scope ?? EMPTY_SCOPE,
  };
}
