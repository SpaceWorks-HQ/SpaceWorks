import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { clearToasts, dismissToast, toastStore, undoToast } from "../../../components/ui/toastStore";
import { useInventoryArchive } from "./useInventoryArchive";
import type { AdminProduct } from "./InventoryPanelShared";
const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest }));
afterEach(() => { toastStore.snapshot().forEach(row => dismissToast(row.id)); staffRequest.mockReset(); });
function mountArchive() {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return renderHook(() => useInventoryArchive(vi.fn(), vi.fn()), { wrapper });
}
it("retires an older undo when a newer change touches the same item", async () => {
  staffRequest.mockResolvedValue({});
  const { result } = mountArchive();
  const product = { id: 9, name: "Drill" } as AdminProduct;
  await act(async () => { await result.current.archive.mutateAsync(product); });
  const older = toastStore.snapshot()[0].id;
  await act(async () => { await result.current.unarchive.mutateAsync(product); });
  await act(async () => { await undoToast(older); });
  expect(staffRequest).toHaveBeenCalledTimes(2);
  await act(async () => { await undoToast(toastStore.snapshot().find(row => row.undo)!.id); });
  expect(staffRequest).toHaveBeenLastCalledWith("/admin/inventory/9", { method: "PATCH", body: JSON.stringify({ is_archived: true }) });
});
it("blocks an overlapping archive while a reversal is still in flight", async () => {
  staffRequest.mockResolvedValueOnce({});
  const { result } = mountArchive();
  const product = { id: 9, name: "Drill" } as AdminProduct;
  await act(async () => { await result.current.archive.mutateAsync(product); });
  let finish!: () => void;
  staffRequest.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
  let reversal!: Promise<void>;
  act(() => { reversal = undoToast(toastStore.snapshot()[0].id); });
  await act(async () => { await expect(result.current.archive.mutateAsync(product)).rejects.toThrow("still in progress"); });
  expect(staffRequest).toHaveBeenCalledTimes(2);
  await act(async () => { finish(); await reversal; });
});
it("does not expose a late archive result to a new authentication session", async () => {
  let finish!: () => void;
  staffRequest.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
  const { result } = mountArchive();
  let pending!: Promise<number>;
  act(() => { pending = result.current.archive.mutateAsync({ id: 9, name: "Private drill" } as AdminProduct); });
  await vi.waitFor(() => expect(staffRequest).toHaveBeenCalled());
  clearToasts();
  await act(async () => { finish(); await pending; });
  expect(toastStore.snapshot()).toEqual([]);
});
it("undoes a successful archive through the real unarchive endpoint and refreshes server state", async () => {
  staffRequest.mockResolvedValue({});
  const invalidate = vi.fn(); const close = vi.fn();
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(() => useInventoryArchive(invalidate, close), { wrapper });
  await act(async () => { await result.current.archive.mutateAsync({ id: 9, name: "Drill" } as AdminProduct); });
  expect(staffRequest).toHaveBeenCalledWith("/admin/inventory/9", { method: "PATCH", body: JSON.stringify({ is_archived: true }) });
  expect(close).toHaveBeenCalledTimes(1); expect(invalidate).toHaveBeenCalledTimes(1);
  await act(async () => { await undoToast(toastStore.snapshot()[0].id); });
  expect(staffRequest).toHaveBeenLastCalledWith("/admin/inventory/9", { method: "PATCH", body: JSON.stringify({ is_archived: false }) });
  expect(invalidate).toHaveBeenCalledTimes(2);
});
