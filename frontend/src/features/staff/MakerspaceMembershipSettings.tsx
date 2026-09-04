import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import type { Makerspace as MakerspaceContract, MembershipPolicyEnum } from "../../generated/api";
import { staffRequest } from "../../lib/api";
import type { Makerspace } from "./StaffPanels";

export function MakerspaceMembershipSettings({ makerspace, settings, loading }: {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
}) {
  const queryClient = useQueryClient();
  const membershipPolicy = settings?.membership_policy ?? makerspace.membership_policy ?? "request";
  const referralsEnabled = settings?.referrals_enabled ?? makerspace.referrals_enabled ?? false;
  const [duesAmount, setDuesAmount] = useState(
    settings?.membership_dues_amount ?? makerspace.membership_dues_amount ?? "0.00",
  );
  useEffect(() => {
    setDuesAmount(settings?.membership_dues_amount ?? makerspace.membership_dues_amount ?? "0.00");
  }, [settings?.membership_dues_amount, makerspace.membership_dues_amount]);
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };
  const updateMembershipPolicy = useMutation({
    mutationFn: (next: MembershipPolicyEnum) => staffRequest<MakerspaceContract>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ membership_policy: next }),
    }),
    onSuccess: refresh,
  });
  const updateReferrals = useMutation({
    mutationFn: (next: boolean) => staffRequest<MakerspaceContract>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ referrals_enabled: next }),
    }),
    onSuccess: refresh,
  });
  const lapsedCannotBorrow = settings?.lapsed_members_cannot_borrow;
  const updateLapsed = useMutation({
    mutationFn: (next: boolean) => staffRequest<MakerspaceContract>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ lapsed_members_cannot_borrow: next }),
    }),
    onSuccess: refresh,
  });
  const updateDues = useMutation({
    mutationFn: () => staffRequest<MakerspaceContract>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ membership_dues_amount: duesAmount }),
    }),
    onSuccess: refresh,
  });

  return <>
    <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(220px,280px)] md:items-start">
        <div className="grid min-w-0 max-w-2xl gap-2">
          <div className="flex flex-wrap items-center gap-2"><h3 className="text-base font-semibold text-ink">Membership joining</h3><Badge tone={membershipPolicy === "invite_only" ? "neutral" : "success"}>{membershipPolicyLabel(membershipPolicy)}</Badge></div>
          <p className="text-sm text-muted">Choose whether people join immediately, request approval, or need an invitation. This only controls self-join; manager invitations remain available.</p>
          {updateMembershipPolicy.error ? <p className="text-sm text-danger" role="alert">{updateMembershipPolicy.error.message}</p> : null}
        </div>
        <select aria-label="Membership joining policy" className="desk-input w-full" value={membershipPolicy} disabled={loading || updateMembershipPolicy.isPending} onChange={(event) => updateMembershipPolicy.mutate(event.target.value as MembershipPolicyEnum)}>
          <option value="open">Join instantly</option><option value="request">Request approval</option><option value="invite_only">Invite-only</option>
        </select>
      </div>
    </div>
    <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
        <div className="grid min-w-0 max-w-2xl gap-2">
          <div className="flex flex-wrap items-center gap-2"><h3 className="text-base font-semibold text-ink">Member referrals</h3><Badge tone={referralsEnabled ? "success" : "neutral"}>{referralsEnabled ? "On" : "Off"}</Badge></div>
          <p className="text-sm text-muted">Allow eligible active members to invite someone. Individual referral permission is managed in the member roster.</p>
          {updateReferrals.error ? <p className="text-sm text-danger" role="alert">{updateReferrals.error.message}</p> : null}
        </div>
        <label className="flex min-w-0 items-start gap-3 text-sm text-ink sm:justify-self-start md:justify-self-end"><input className="mt-1 h-4 w-4" type="checkbox" checked={referralsEnabled} disabled={loading || updateReferrals.isPending} onChange={(event) => updateReferrals.mutate(event.target.checked)} /><span className="font-semibold">Enable referrals</span></label>
      </div>
    </div>
    {lapsedCannotBorrow !== undefined ? <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
        <div className="grid min-w-0 max-w-2xl gap-2">
          <div className="flex flex-wrap items-center gap-2"><h3 className="text-base font-semibold text-ink">Lapsed members</h3><Badge tone={lapsedCannotBorrow ? "warn" : "neutral"}>{lapsedCannotBorrow ? "Cannot borrow" : "Can borrow"}</Badge></div>
          <p className="text-sm text-muted">When on, a member whose plan term has expired or was cancelled cannot submit borrow requests until a new term is started.</p>
          {updateLapsed.error ? <p className="text-sm text-danger" role="alert">{updateLapsed.error.message}</p> : null}
        </div>
        <label className="flex min-w-0 items-start gap-3 text-sm text-ink sm:justify-self-start md:justify-self-end"><input className="mt-1 h-4 w-4" type="checkbox" checked={lapsedCannotBorrow} disabled={loading || updateLapsed.isPending} onChange={(event) => updateLapsed.mutate(event.target.checked)} /><span className="font-semibold">Lapsed members cannot borrow</span></label>
      </div>
    </div> : null}
    <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(220px,280px)] md:items-start">
        <div className="grid min-w-0 max-w-2xl gap-2">
          <h3 className="text-base font-semibold text-ink">Membership dues</h3>
          <p className="text-sm text-muted">Set the amount charged when a membership is activated. Use 0 for no charge.</p>
          {updateDues.error ? <p className="text-sm text-danger" role="alert">{updateDues.error.message}</p> : null}
        </div>
        <form className="grid gap-2" onSubmit={(event) => { event.preventDefault(); updateDues.mutate(); }}>
          <label className="grid gap-1 text-sm font-semibold text-ink">Dues amount
            <input className="desk-input" type="number" min="0" step="0.01" value={duesAmount} disabled={loading || updateDues.isPending} onChange={(event) => setDuesAmount(event.target.value)} />
          </label>
          <button className="desk-button" type="submit" disabled={loading || updateDues.isPending}>{updateDues.isPending ? "Saving..." : "Save dues"}</button>
        </form>
      </div>
    </div>
  </>;
}

function membershipPolicyLabel(policy: MembershipPolicyEnum) {
  return { open: "Join instantly", request: "Request approval", invite_only: "Invite-only" }[policy];
}
