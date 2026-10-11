import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DirectHandoverWizard } from "./DirectHandoverWizard";
import { StaffListContext } from "../StaffListContext";
import { expectNoA11yViolations } from "../../../test/axe";

const { request, resolveCard } = vi.hoisted(() => ({ request: vi.fn(), resolveCard: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest: request }));
vi.mock("../../../components/ui/QrScanner", () => ({ default: () => <p>Camera scanner</p> }));
vi.mock("../panels/EvidenceUpload", () => ({ EvidenceUpload: ({ onUploaded }: { onUploaded: (id: number) => void }) => <button onClick={() => onUploaded(9)}>Upload photo</button> }));
vi.mock("../panels/memberCards/api", () => ({ useResolveCard: () => ({ mutateAsync: resolveCard, isPending: false }) }));
vi.mock("../../inventory/KitChecklist", () => ({ useKitChecklist: () => ({ ready: true, counts: [] }), KitChecklistCapture: () => null }));
vi.mock("../panels/shared", () => ({ useStaffGet: (_: unknown, path: string) => ({ data: { results: path.includes("direct-loan-members") ? [{ user_id: 3, membership_id: 8, display_name: "Ada", username: "ada" }] : [{ id: 2, name: "Drill", available_quantity: 4, tracking_mode: "bulk", is_archived: false }] } }) }));
beforeEach(() => { request.mockReset(); request.mockResolvedValue({ id: 12 }); resolveCard.mockReset(); });
function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><StaffListContext.Provider value={{ ownerName: "desk", canShare: false, actions: ["scan_member_cards"] }}><DirectHandoverWizard makerspace={{ id: 1, name: "Lab", slug: "lab", public_code: "LAB1", telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false }} onClose={vi.fn()} /></StaffListContext.Provider></QueryClientProvider>);
}
it("requires an eligible borrower, whole tool quantities and issue photo before writing a receipt", async () => {
  const { container } = mount();
  expect(screen.getByText("Next")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Borrower"), { target: { value: "3" } }); fireEvent.click(screen.getByText("Next"));
  fireEvent.change(screen.getByLabelText("Drill"), { target: { value: "1.5" } }); expect(screen.getByText("Next")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Drill"), { target: { value: "2" } }); fireEvent.click(screen.getByText("Next"));
  expect(screen.getByText("Confirm handout")).toBeDisabled(); expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Upload photo")); await expectNoA11yViolations(container);
  fireEvent.click(screen.getByText("Confirm handout")); await screen.findByText("Handout #12 recorded");
  expect(request).toHaveBeenCalledWith("/admin/makerspace/1/direct-loans", expect.any(Object));
  expect(JSON.parse(request.mock.calls[0][1].body)).toMatchObject({ borrower_id: 3, evidence_id: 9, items: [{ product_id: 2, quantity: 2 }] });
  expect(screen.getByText("Drill × 2")).toBeInTheDocument();
});
it("refuses revoked or foreign member cards without selecting a borrower", async () => {
  resolveCard.mockResolvedValue({ outcome: "revoked" }); mount();
  fireEvent.change(screen.getByLabelText("Card payload"), { target: { value: "CARD" } }); fireEvent.click(screen.getByText("Check card"));
  await screen.findByRole("alert"); expect(screen.getByText("Next")).toBeDisabled();
  resolveCard.mockResolvedValue({ outcome: "ok", membership_id: 99 }); fireEvent.click(screen.getByText("Check card"));
  await waitFor(() => expect(resolveCard).toHaveBeenCalledTimes(2)); expect(screen.getByLabelText("Borrower")).toHaveValue("");
  resolveCard.mockResolvedValue({ outcome: "ok", membership_id: 8 }); fireEvent.click(screen.getByText("Check card"));
  await waitFor(() => expect(screen.getByLabelText("Borrower")).toHaveValue("3"));
});
it("rejects a box QR as a direct-handout tool", async () => {
  request.mockResolvedValue({ qr: { makerspace: 1 }, target: { type: "box" } }); mount();
  fireEvent.change(screen.getByLabelText("Borrower"), { target: { value: "3" } }); fireEvent.click(screen.getByText("Next"));
  fireEvent.change(screen.getByLabelText("Tool QR payload"), { target: { value: "BOX" } }); fireEvent.click(screen.getByText("Check tool QR"));
  await screen.findByText("Scan a tool or asset QR in this flow."); expect(screen.getByText("Next")).toBeDisabled();
});

it("rejects a foreign tool and an unavailable tool and refuses quantities above availability", async () => {
  mount();
  fireEvent.change(screen.getByLabelText("Borrower"), { target: { value: "3" } }); fireEvent.click(screen.getByText("Next"));
  fireEvent.change(screen.getByLabelText("Drill"), { target: { value: "5" } });
  expect(screen.getByText("Next")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Drill"), { target: { value: "" } });
  fireEvent.change(screen.getByLabelText("Tool QR payload"), { target: { value: "TOOL" } });
  request.mockResolvedValue({ qr: { makerspace: 2 }, target: { type: "product", id: 2 }, allowed_actions: ["direct_handout"] });
  fireEvent.click(screen.getByText("Check tool QR")); await screen.findByText("Scan a tool from this makerspace.");
  expect(screen.getByText("Next")).toBeDisabled();
  request.mockResolvedValue({ qr: { makerspace: 1 }, target: { type: "asset", id: 2 }, allowed_actions: ["view", "return"] });
  fireEvent.click(screen.getByText("Check tool QR")); await screen.findByText("This tool is unavailable for direct handout.");
  expect(screen.getByText("Next")).toBeDisabled();
  request.mockResolvedValue({ qr: { makerspace: 1 }, target: { type: "product", id: 2 }, allowed_actions: ["direct_handout"] });
  fireEvent.click(screen.getByText("Check tool QR")); await waitFor(() => expect(screen.getByText("Next")).toBeEnabled());
});
