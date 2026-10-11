import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { HandoverWizard } from "./HandoverWizard";
import type { HardwareRequest } from "../panels/Queues";
import { expectNoA11yViolations } from "../../../test/axe";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest: request }));
vi.mock("../../../components/ui/QrScanner", () => ({ default: ({ feedback, onScan }: { feedback?: ReactNode; onScan: (value: string) => void }) => <div data-testid="camera-feedback">{feedback}<button onClick={() => onScan("ASSET")}>Read asset</button></div> }));
vi.mock("../panels/EvidenceUpload", () => ({ EvidenceUpload: ({ onUploaded }: { onUploaded: (id: number) => void }) => <button onClick={() => onUploaded(4)}>Upload photo</button> }));
vi.mock("../panels/memberCards/ScanCardBox", () => ({ ScanCardBox: () => <p>Card scan</p> }));
vi.mock("../../inventory/KitChecklist", () => ({ useKitChecklist: () => ({ ready: true, counts: [] }), KitChecklistCapture: () => null }));
const row = { id: 7, requester_username: "ada", requester_display: "Ada", status: "accepted", requested_for: "Test", return_due_at: null, return_reminder_sent_at: null,
  items: [{ id: 1, product_id: 2, product_name: "Drill", storage_location: "Desk", tracking_mode: "bulk", requires_asset_qr: false, requested_quantity: 1, accepted_quantity: 1, issued_quantity: 1, returned_quantity: 0, damaged_quantity: 0, missing_quantity: 0, needs_fix_quantity: 0 }] } satisfies HardwareRequest;
beforeEach(() => { request.mockReset(); request.mockImplementation((path: string) => Promise.resolve(path === "/admin/qr/resolve" ? { qr: { makerspace: 1 }, target: { type: "box", code: "BX01" } } : {})); });
function mount(mode: "issue" | "return", requestRow: HardwareRequest = row) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><HandoverWizard row={requestRow} makerspace={{ id: 1, name: "Lab", slug: "lab", public_code: "LAB1", telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false }} mode={mode} onClose={vi.fn()} /></QueryClientProvider>);
}
async function advanceToPhoto() {
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Box QR payload"), { target: { value: "BOX:BX01" } });
  fireEvent.click(screen.getByText("Check box QR")); await screen.findByText("Verified box: BX01");
  fireEvent.click(screen.getByText("Next"));
  fireEvent.click(screen.getByLabelText("I checked the borrower against this request"));
  fireEvent.click(screen.getByText("Next")); fireEvent.click(screen.getByText("Next"));
}
it("cannot issue without verified box scan and photo; receipt follows both workflow calls", async () => {
  const { container } = mount("issue"); await advanceToPhoto();
  expect(screen.getByRole("button", { name: "Confirm issue" })).toBeDisabled();
  fireEvent.click(screen.getByText("Upload photo")); await expectNoA11yViolations(container);
  fireEvent.click(screen.getByText("Confirm issue")); await screen.findByText("Issue recorded");
  expect(request.mock.calls.map(call => call[0])).toEqual(["/admin/qr/resolve", "/admin/requests/7/assign-box", "/admin/requests/7/issue"]);
  expect(JSON.parse(request.mock.calls[2][1].body)).toMatchObject({ evidence_id: 4 });
});
it("cannot return without both a photo and remark", async () => {
  mount("return"); await advanceToPhoto();
  fireEvent.click(screen.getByText("Upload photo")); expect(screen.getByText("Confirm return")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Return remark (required)"), { target: { value: "All tools checked" } });
  fireEvent.click(screen.getByText("Confirm return")); await screen.findByText("Return recorded");
  expect(JSON.parse(request.mock.calls[1][1].body)).toMatchObject({ evidence_id: 4, remark: "All tools checked", resolutions: [{ item_id: 1, returned: 1 }] });
});
it("shows partial assignment failure without a receipt and allows retry", async () => {
  request.mockImplementation((path: string) => path.endsWith("/issue") ? Promise.reject(new Error("Evidence missing in storage")) : Promise.resolve(path === "/admin/qr/resolve" ? { qr: { makerspace: 1 }, target: { type: "box", code: "BX01" } } : {}));
  mount("issue"); await advanceToPhoto(); fireEvent.click(screen.getByText("Upload photo")); fireEvent.click(screen.getByText("Confirm issue"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Box assignment was recorded"));
  expect(screen.queryByText("Issue recorded")).not.toBeInTheDocument(); expect(screen.getByText("Confirm issue")).toBeEnabled();
});

it("refuses a container resolved in another tenant without advancing", async () => {
  request.mockResolvedValue({ qr: { makerspace: 2 }, target: { type: "box", code: "FOREIGN" } });
  mount("issue");
  fireEvent.change(screen.getByLabelText("Box QR payload"), { target: { value: "FOREIGN" } });
  fireEvent.click(screen.getByText("Check box QR"));
  await screen.findByText("Scan a container from this makerspace.");
  expect(screen.getByText("Next")).toBeDisabled();
  expect(request).toHaveBeenCalledTimes(1);
});

it("shows continuous scan progress and refusal feedback while the camera stays open", async () => {
  mount("issue", { ...row, items: [{ ...row.items[0], tracking_mode: "individual", requires_asset_qr: true }] });
  fireEvent.change(screen.getByLabelText("Box QR payload"), { target: { value: "BOX" } });
  fireEvent.click(screen.getByText("Check box QR")); await screen.findByText("Verified box: BX01");
  fireEvent.click(screen.getByText("Next")); fireEvent.click(screen.getByLabelText("I checked the borrower against this request")); fireEvent.click(screen.getByText("Next"));
  expect(screen.getByText("Next")).toBeDisabled();
  fireEvent.click(screen.getByText("Scan items continuously"));
  const camera = within(screen.getByTestId("camera-feedback"));
  request.mockResolvedValue({ qr: { makerspace: 1 }, target: { type: "asset", status: "issued" } });
  fireEvent.click(camera.getByText("Read asset"));
  expect(await camera.findByRole("alert")).toHaveTextContent("This asset is unavailable for issue.");
  expect(camera.getByRole("status")).toHaveTextContent("0 / 1");
  request.mockResolvedValue({ qr: { makerspace: 1 }, target: { type: "asset", status: "available" } });
  fireEvent.click(camera.getByText("Read asset"));
  await waitFor(() => expect(camera.getByRole("status")).toHaveTextContent("1 / 1"));
  expect(screen.getByText("Next")).toBeEnabled();
});
