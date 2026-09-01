import { useState } from "react";


export type ClaimableInvitation = {
  id: number;
  makerspace: { slug: string; name: string };
  inviter: string | null;
  auto_activates: boolean;
  role: string | null;
};

type Props = {
  canRefer: boolean;
  referralsEnabled: boolean;
  emailVerified: boolean | undefined;
  invitations: ClaimableInvitation[];
  invitationsLoading: boolean;
  invitationError?: Error | null;
  onRefer: (email: string) => Promise<unknown>;
  onClaim: (id: number) => void;
  isReferring?: boolean;
  claimingId?: number | null;
  referralError?: Error | null;
  referralSuccess?: string | null;
  claimError?: Error | null;
  claimSuccess?: string | null;
};


export function MemberReferrals({
  canRefer, referralsEnabled, emailVerified, invitations, invitationsLoading, invitationError,
  onRefer, onClaim, isReferring = false, claimingId, referralError, referralSuccess, claimError,
  claimSuccess,
}: Props) {
  const [email, setEmail] = useState("");
  const canSubmitReferral = referralsEnabled && canRefer;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await onRefer(email);
      setEmail("");
    } catch {
      // The mutation state renders the user-facing error below.
    }
  }

  return <div className="space-y-5">
    {canSubmitReferral ? <section className="desk-panel p-5">
      <h2 className="title-panel">Refer someone</h2>
      <p className="mt-1 text-sm text-muted">Invite someone by email to join as a member.</p>
      <form className="mt-4 flex flex-col gap-3 sm:flex-row" onSubmit={submit}>
        <label className="sr-only" htmlFor="member-referral-email">Invite email</label>
        <input id="member-referral-email" className="desk-input flex-1" type="email" required value={email}
          onChange={(event) => setEmail(event.target.value)} placeholder="friend@example.com" />
        <button className="desk-button-secondary" disabled={isReferring} type="submit">
          {isReferring ? "Sending…" : "Send referral"}
        </button>
      </form>
      {referralSuccess ? <p className="mt-3 text-sm text-success" role="status">{referralSuccess}</p> : null}
      {referralError ? <p className="mt-3 text-sm text-danger" role="alert">{referralError.message}</p> : null}
    </section> : null}

    <section className="desk-panel p-5">
      <h2 className="title-panel">Pending invitations</h2>
      {emailVerified === false ? <p className="mt-2 text-sm text-muted">Verify your email to discover and claim invitations.</p> : null}
      {invitationsLoading ? <p className="mt-2 text-sm text-muted">Checking pending invitations…</p> : null}
      {invitationError ? <p className="mt-2 text-sm text-danger" role="alert">{invitationError.message}</p> : null}
      {emailVerified !== false && !invitationsLoading && invitations.length === 0 ? <p className="mt-2 text-sm text-muted">No pending invitations for this makerspace.</p> : null}
      {emailVerified !== false && invitations.length ? <ul className="mt-3 space-y-3">
        {invitations.map((invitation) => <li className="rounded border border-line p-3" key={invitation.id}>
          <p className="text-sm font-medium text-ink">{invitation.makerspace.name}</p>
          <p className="mt-1 text-sm text-muted">{invitation.inviter ? `Invited by ${invitation.inviter}` : "You have been invited."}{invitation.auto_activates ? " Claiming activates your membership." : " Claiming sends this to a manager for approval."}</p>
          <button className="desk-button-secondary mt-3" disabled={claimingId === invitation.id} onClick={() => onClaim(invitation.id)}>
            {claimingId === invitation.id ? "Claiming…" : "Claim invitation"}
          </button>
        </li>)}
      </ul> : null}
      {claimSuccess ? <p className="mt-3 text-sm text-success" role="status">{claimSuccess}</p> : null}
      {claimError ? <p className="mt-3 text-sm text-danger" role="alert">{claimError.message}</p> : null}
    </section>
  </div>;
}
