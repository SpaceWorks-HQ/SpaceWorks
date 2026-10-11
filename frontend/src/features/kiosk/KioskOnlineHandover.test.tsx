import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KioskOnlineHandover } from "./KioskOnlineHandover";
import * as api from "./kioskApi";

vi.mock("./kioskApi", () => ({ loadWorkPackage: vi.fn(), prepareEvidence: vi.fn(), runOnlineCommand: vi.fn() }));
vi.mock("../staff/panels/EvidenceUpload", () => ({ EvidenceUpload: ({ onUploaded }: { onUploaded: (id: number) => void }) =>
  <button type="button" onClick={() => onUploaded(7)}>Upload photo</button> }));

describe("kiosk kit capture", () => {
  it("keeps the issue blocked until counted and forwards physical counts with evidence", async () => {
    vi.mocked(api.loadWorkPackage).mockResolvedValue({ kind: "reviewed_request", id: 4,
      status: "accepted", display_label: "Request #4", person_display: "Member", box: "Tool box",
      lines: [{ item_id: 5, label: "Driver", quantity: 1, returned: 0 }],
      kit_components: [{ key: "bits", label: "Bits", owner_label: "Driver", quantity: 12 }],
      return_resolutions: ["returned"], expires_at: "2999-01-01T00:00:00Z",
      command_age_limit_seconds: 3600, evidence_max_bytes: 10000 });
    vi.mocked(api.runOnlineCommand).mockResolvedValue({ kind: "reviewed_issue", result: {} });
    render(<KioskOnlineHandover token="desk" makerspaceId={1} lease={{ lease_token: "lease", lease_id: "id",
      expires_at: "2999-01-01T00:00:00Z", allowed_actions: [], permitted_operations: ["reviewed_issue"] }} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Request number" }), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Load request" }));
    fireEvent.click(await screen.findByRole("button", { name: "Upload photo" }));
    expect(screen.getByRole("button", { name: "Issue items" })).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "11" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Issue items" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Issue items" }));
    await waitFor(() => expect(api.runOnlineCommand).toHaveBeenCalledWith("desk", "lease", "reviewed_issue",
      expect.objectContaining({ request_id: 4, evidence_id: 7, kit_checklist: [{ key: "bits", present: 11 }] })));
  });
});
