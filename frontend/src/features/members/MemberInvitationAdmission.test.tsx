import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemberReferrals } from "./MemberReferrals";

const invitation = { id: 21, makerspace: { slug: "workshop", name: "Workshop" }, inviter: "Sam", auto_activates: true, role: "Member" };
describe("invitation admission conditions", () => {
  it("claims a staff invitation without community application answers", () => {
    const claim = vi.fn();
    render(<MemberReferrals canRefer={false} referralsEnabled={false} emailVerified invitations={[{ ...invitation, is_staff: true, auto_activates: false }]} invitationsLoading={false} onRefer={vi.fn()} onClaim={claim} admissionMode="approval" applicationSchema={[{ id: "why", label: "Why join?", type: "short_text", required: true, options: [] }]} />);
    expect(screen.queryByLabelText(/Why join/)).toBeNull();
    expect(screen.getByText(/Claiming sends this to a manager for approval/)).toBeVisible();
    fireEvent.submit(screen.getByRole("button", { name: "Claim invitation" }).closest("form")!);
    expect(claim).toHaveBeenCalledWith(21);
  });
  it("collects answers on claim and does not promise immediate activation", () => {
    const claim = vi.fn();
    render(<MemberReferrals canRefer={false} referralsEnabled={false} emailVerified invitations={[invitation]} invitationsLoading={false} onRefer={vi.fn()} onClaim={claim} admissionMode="invite_only" applicationSchema={[{ id: "why", label: "Why join?", type: "short_text", required: true, options: [] }]} />);
    expect(screen.getByText(/Admission conditions apply when you claim/)).toBeVisible();
    fireEvent.submit(screen.getByRole("button", { name: "Claim invitation" }).closest("form")!);
    expect(claim).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Why join/), { target: { value: "Learn making" } });
    fireEvent.submit(screen.getByRole("button", { name: "Claim invitation" }).closest("form")!);
    expect(claim).toHaveBeenCalledWith(21, { why: "Learn making" });
  });
  it("hides referral and claim actions when admissions are closed", () => {
    render(<MemberReferrals canRefer referralsEnabled emailVerified invitations={[invitation]} invitationsLoading={false} onRefer={vi.fn()} onClaim={vi.fn()} admissionMode="closed" />);
    expect(screen.getByText("Membership applications are closed.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Claim invitation" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Send referral" })).toBeNull();
  });
});
