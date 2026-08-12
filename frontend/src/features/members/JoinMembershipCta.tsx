import type { MembershipPolicyEnum } from "../../generated/api";

export type JoinCtaState = {
  title: string;
  description: string;
  action: "join" | "sign_in" | "none";
  actionLabel?: string;
};

export function joinCtaState(policy: MembershipPolicyEnum, signedIn: boolean): JoinCtaState {
  if (policy === "invite_only") {
    return {
      title: "Invite-only makerspace",
      description: "This makerspace does not accept self-join requests. Ask a space manager for an invitation.",
      action: "none",
    };
  }
  const instantly = policy === "open";
  return {
    title: "Join this makerspace",
    description: instantly ? "You will become a member immediately." : "Your request will be sent to staff for approval.",
    action: signedIn ? "join" : "sign_in",
    actionLabel: signedIn ? (instantly ? "Join instantly" : "Request to join") : "Sign in to join",
  };
}

export function JoinMembershipCta({ policy, signedIn, pending, onJoin, onSignIn }: {
  policy: MembershipPolicyEnum;
  signedIn: boolean;
  pending: boolean;
  onJoin: () => void;
  onSignIn: () => void;
}) {
  const state = joinCtaState(policy, signedIn);
  return <section className="desk-panel p-5">
    <h2 className="title-panel">{state.title}</h2>
    <p className="mt-1 text-sm text-muted">{state.description}</p>
    {state.action !== "none" ? <button className="desk-button-secondary mt-4" type="button" disabled={pending} onClick={state.action === "join" ? onJoin : onSignIn}>
      {pending && state.action === "join" ? "Sending…" : state.actionLabel}
    </button> : null}
  </section>;
}
