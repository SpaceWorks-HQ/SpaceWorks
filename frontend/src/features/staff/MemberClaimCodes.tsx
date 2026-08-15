import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { Panel } from "./panels/shared";

export type ClaimableMember = {
  membership_id: number;
  user_id: number;
  display_name: string;
  username: string;
  is_walk_in: boolean;
};

type ClaimCode = {
  id: number;
  membership_id: number;
  member_display_name: string;
  issued_by_id: number | null;
  issued_at: string;
  expires_at: string;
  consumed_at: string | null;
  revoked_at: string | null;
  status: "issued" | "consumed" | "revoked";
};

type IssuedClaimCode = ClaimCode & { code: string; qr_svg: string };

export function MemberClaimCodes({
  makerspaceId,
  members,
}: {
  makerspaceId: number;
  members: ClaimableMember[];
}) {
  const queryClient = useQueryClient();
  const queryKey = ["member-claim-codes", makerspaceId];
  const [membershipId, setMembershipId] = useState("");
  const [issued, setIssued] = useState<IssuedClaimCode | null>(null);
  useEffect(() => {
    setMembershipId("");
    setIssued(null);
  }, [makerspaceId]);
  const active = useQuery({
    queryKey,
    queryFn: () =>
      staffRequest<ClaimCode[]>(
        `/admin/makerspaces/${makerspaceId}/member-claim-codes`,
      ),
  });
  const issue = useMutation({
    mutationFn: () =>
      staffRequest<IssuedClaimCode>(
        `/admin/makerspaces/${makerspaceId}/member-claim-codes`,
        {
          method: "POST",
          body: JSON.stringify({ membership_id: Number(membershipId) }),
        },
      ),
    onSuccess: (claim) => {
      setIssued(claim);
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const revoke = useMutation({
    mutationFn: (claimId: number) =>
      staffRequest<ClaimCode>(
        `/admin/makerspaces/${makerspaceId}/member-claim-codes/${claimId}/revoke`,
        { method: "POST" },
      ),
    onSuccess: (claim) => {
      if (issued?.id === claim.id) setIssued(null);
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const walkIns = members.filter((member) => member.is_walk_in);
  const error = issue.error ?? revoke.error;

  return (
    <Panel title="Member claim code">
      <p className="text-sm text-muted">
        Issue only while the walk-in is physically present. Hand over the code or QR;
        never email or text it.
      </p>
      <div className="mt-3 flex flex-col gap-2 md:flex-row">
        <select
          aria-label="Walk-in member"
          className="desk-input w-full"
          value={membershipId}
          onChange={(event) => setMembershipId(event.target.value)}
        >
          <option value="">Select an eligible walk-in</option>
          {walkIns.map((member) => (
            <option key={member.membership_id} value={member.membership_id}>
              {member.display_name || member.username}
            </option>
          ))}
        </select>
        <button
          className="desk-button-primary"
          type="button"
          disabled={!membershipId || issue.isPending}
          onClick={() => issue.mutate()}
        >
          {issue.isPending ? "Issuing…" : "Issue claim code"}
        </button>
      </div>
      {issued ? (
        <div className="mt-4 grid gap-4 rounded-lg border border-line bg-surface p-4 md:grid-cols-[1fr_180px]">
          <div>
            <p className="text-sm font-semibold text-ink">Hand this to {issued.member_display_name}</p>
            <p className="mt-2 break-all font-mono text-lg font-semibold text-ink">{issued.code}</p>
            <p className="mt-2 text-xs text-muted">
              Expires {new Date(issued.expires_at).toLocaleString()}. This code will not be shown again after you leave this view.
            </p>
          </div>
          <img
            className="aspect-square w-full rounded-md border border-line bg-white p-2"
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(issued.qr_svg)}`}
            alt={`Claim code QR for ${issued.member_display_name}`}
          />
        </div>
      ) : null}
      <div className="mt-4 grid gap-2">
        {active.data?.map((claim) => (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3" key={claim.id}>
            <div>
              <p className="text-sm font-medium text-ink">{claim.member_display_name}</p>
              <p className="text-xs text-muted">Expires {new Date(claim.expires_at).toLocaleString()}</p>
            </div>
            <button className="desk-button" type="button" disabled={revoke.isPending} onClick={() => revoke.mutate(claim.id)}>
              Revoke
            </button>
          </div>
        ))}
        {active.isLoading ? <p className="text-sm text-muted">Loading active claim codes…</p> : null}
        {!active.isLoading && !active.data?.length ? <p className="text-sm text-muted">No active claim codes.</p> : null}
      </div>
      {active.error ? <p className="mt-3 text-sm text-danger" role="alert">{active.error.message}</p> : null}
      {error ? <p className="mt-3 text-sm text-danger" role="alert">{error.message}</p> : null}
    </Panel>
  );
}
