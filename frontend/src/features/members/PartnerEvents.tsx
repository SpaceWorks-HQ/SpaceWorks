import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { CollaborativeEvent } from "../../generated/api";
import { CustomFormFields } from "../forms/CustomFormFields";
import type { CustomAnswers, CustomFormSchema } from "../forms/customFormTypes";
import { staffRequest } from "../../lib/api";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/** Events hosted by makerspaces that have accepted a collaboration with this one.
 *
 * Discovery has its own member-scoped endpoint rather than widening the public event list:
 * that list is `AllowAny` and shared with public registration, so relaxing its `is_public`
 * filter would publish a members-only event to the world. Renders nothing when there is
 * nothing to show, so a space with no partners sees no new section.
 */
export function PartnerEvents({
  makerspaceId,
  slug,
}: {
  makerspaceId: number;
  slug: string;
}) {
  const queryClient = useQueryClient();
  const events = useQuery({
    queryKey: ["member", slug, "partner-events"],
    queryFn: () => staffRequest<CollaborativeEvent[]>(
      `/member/makerspaces/${makerspaceId}/collaborative-events/`,
    ),
    enabled: makerspaceId >= 0,
    retry: false,
  });
  const [openId, setOpenId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const register = useMutation({
    mutationFn: ({ eventId, custom_answers }: { eventId: number; custom_answers: CustomAnswers }) =>
      staffRequest<{ status: string }>(
        `/member/makerspaces/${makerspaceId}/collaborative-events/${eventId}/register/`,
        { method: "POST", body: JSON.stringify({ custom_answers }) },
      ),
    onSuccess: async () => { await Promise.all([
      // The activity payload carries the new registration and its check-in QR token, so it
      // has to be refetched or the member sees no code for the event they just joined.
      queryClient.invalidateQueries({ queryKey: ["member", slug, "activity"] }),
      queryClient.invalidateQueries({ queryKey: ["member", slug, "partner-events"] }),
    ]); setOpenId(null); setAnswers({}); },
  });

  const rows = events.data ?? [];
  if (!rows.length) return null;

  return (
    <section className="desk-panel p-5" aria-labelledby="partner-events-title">
      <h2 id="partner-events-title" className="font-semibold text-ink">
        Events at partner makerspaces
      </h2>
      <p className="mt-1 text-sm text-muted">
        Your makerspace collaborates with these hosts, so you can register even when the
        event is not listed publicly.
      </p>
      <ul className="mt-3 space-y-3 text-sm">
        {rows.map((event) => {
          // A host may attach a custom form, and the backend validates required answers.
          // Without rendering those fields the button would post `{}` and such an event
          // would simply be unregisterable through this surface.
          const schema = (event.custom_form ?? null) as CustomFormSchema | null;
          const needsAnswers = Boolean(schema?.length);
          const open = openId === event.id;
          return (
            <li key={event.id} className="border-t border-line pt-3 first:border-0 first:pt-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  <span className="font-medium text-ink">{event.title}</span>
                  <span className="block text-muted">
                    Hosted by {event.host_name} · {new Date(event.starts_at).toLocaleString()}
                  </span>
                </span>
                <button
                  type="button"
                  className={`desk-button ${FOCUS}`}
                  disabled={register.isPending}
                  onClick={() => {
                    if (needsAnswers && !open) {
                      setAnswers({});
                      setOpenId(event.id);
                      return;
                    }
                    register.mutate({ eventId: event.id, custom_answers: open ? answers : {} });
                  }}
                >
                  {needsAnswers && !open ? "Register…" : "Register"}
                </button>
              </div>
              {/* Unmounted when closed rather than hidden, so keyboard users cannot tab
                  into fields for an event they are not registering for. */}
              {open && schema ? (
                <div className="mt-3">
                  <CustomFormFields schema={schema} answers={answers} onChange={setAnswers} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {register.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {register.error instanceof Error ? register.error.message : "Could not register."}
        </p>
      ) : null}
    </section>
  );
}
