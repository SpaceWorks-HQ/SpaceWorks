import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";

type WalkInMember = { user_id: number; display_name: string; username: string };

/**
 * Name the person at the counter so a handout can be recorded against them.
 *
 * This is the identity path a deployment running without member accounts lives on, so
 * it sits inside the handout flow rather than relying on self-service enrolment.
 *
 * Collapsed by default. The normal case is picking an existing member, and an always-open
 * creation form next to a dropdown invites creating a duplicate of the person already in it.
 */
export function WalkInMemberForm({
  makerspaceId,
  onCreated,
}: {
  makerspaceId: number;
  onCreated: (userId: number) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");

  const create = useMutation({
    mutationFn: () =>
      staffRequest<WalkInMember>(`/admin/makerspaces/${makerspaceId}/walk-in-members`, {
        method: "POST",
        body: JSON.stringify({
          display_name: displayName.trim(),
          email: email.trim(),
          phone: phone.trim(),
        }),
      }),
    onSuccess: (member) => {
      // The dropdown reads this query, so it has to be refetched before the new member
      // can be selected — selecting an id the options don't contain leaves the select blank.
      void queryClient
        .invalidateQueries({ queryKey: ["direct-loan-members", makerspaceId] })
        .then(() => onCreated(member.user_id));
      setDisplayName("");
      setEmail("");
      setPhone("");
      setOpen(false);
    },
  });

  if (!open) {
    return (
      <button
        className="desk-button-ghost mt-2 px-0"
        type="button"
        onClick={() => setOpen(true)}
      >
        Not a member yet? Add a walk-in
      </button>
    );
  }

  return (
    <div className="mt-3 rounded-lg border border-line bg-surface p-3">
      <p className="text-sm font-medium text-ink">Add a walk-in</p>
      <p className="mt-1 text-xs text-muted">
        Creates a person record for the handover trail. It is not an account and cannot sign in.
      </p>
      <label className="mt-3 block text-sm font-medium text-ink" htmlFor="walk-in-name">
        Name
      </label>
      <input
        id="walk-in-name"
        className="desk-input mt-1 w-full"
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
      />
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <div>
          <label className="block text-sm font-medium text-ink" htmlFor="walk-in-email">
            Email <span className="font-normal text-muted">(optional)</span>
          </label>
          <input
            id="walk-in-email"
            className="desk-input mt-1 w-full"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-ink" htmlFor="walk-in-phone">
            Phone <span className="font-normal text-muted">(optional)</span>
          </label>
          <input
            id="walk-in-phone"
            className="desk-input mt-1 w-full"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
          />
        </div>
      </div>
      {create.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {create.error instanceof Error ? create.error.message : "Unable to add the walk-in."}
        </p>
      ) : null}
      <div className="mt-3 flex gap-2">
        <button
          className="desk-button-primary"
          type="button"
          disabled={!displayName.trim() || create.isPending}
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Adding…" : "Add walk-in"}
        </button>
        <button className="desk-button" type="button" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}
