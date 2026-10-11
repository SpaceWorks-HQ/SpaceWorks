import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastHost } from "./ToastHost";
import { clearToasts, dismissToast, toast, toastStore, undoToast } from "./toastStore";
import { expectNoA11yViolations } from "../../test/axe";

beforeEach(() => { toastStore.snapshot().forEach(row => dismissToast(row.id)); vi.useFakeTimers(); });
afterEach(() => { toastStore.snapshot().forEach(row => dismissToast(row.id)); vi.useRealTimers(); });

describe("toast undo and announcer", () => {
  it("keeps a pending announcement when undo updates only the busy state", async () => {
    let finish!: () => void;
    render(<ToastHost />);
    act(() => { toast("Archived", { undo: () => new Promise<void>(resolve => { finish = resolve; }) }); });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    act(() => { vi.advanceTimersByTime(50); });
    expect(screen.getByRole("status")).toHaveTextContent("Archived");
    await act(async () => { finish(); });
  });
  it("clears private messages and suppresses an in-flight undo result after sign-out", async () => {
    let finish!: () => void;
    render(<ToastHost />);
    act(() => { toast("Private item archived", { undo: () => new Promise<void>(resolve => { finish = resolve; }) }); });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    act(() => { clearToasts(); vi.advanceTimersByTime(50); });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    await act(async () => { finish(); });
    expect(toastStore.snapshot()).toEqual([]);
  });
  it("expires the undo window without calling a reversal", () => {
    const undo = vi.fn(); render(<ToastHost />);
    act(() => { toast("Archived", { undo }); });
    expect(screen.getByRole("button", { name: "Undo" })).toBeVisible();
    act(() => { vi.advanceTimersByTime(7999); });
    expect(screen.getByRole("button", { name: "Undo" })).toBeVisible();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(undo).not.toHaveBeenCalled();
  });
  it("waits for the compensating call and refuses a double undo", async () => {
    let finish!: () => void;
    const undo = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    let id = 0; render(<ToastHost />);
    act(() => { id = toast("Archived", { undo }); });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByRole("button", { name: "Undoing…" })).toBeDisabled();
    await act(async () => { await undoToast(id); vi.advanceTimersByTime(10000); });
    expect(undo).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Action undone.")).not.toBeInTheDocument();
    await act(async () => { finish(); });
    expect(screen.getByText("Action undone.")).toBeVisible();
  });
  it("keeps a failed reversal visible and never claims success", async () => {
    render(<ToastHost />);
    act(() => { toast("Archived", { undo: async () => { throw new Error("Permission changed"); } }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Undo" })); });
    act(() => { vi.advanceTimersByTime(20000); });
    expect(within(screen.getByRole("complementary", { name: "Notifications" })).getByText("Could not undo: Permission changed")).toBeVisible();
    expect(screen.queryByText("Action undone.")).not.toBeInTheDocument();
  });
  it("announces async results and repeated messages without moving focus", () => {
    render(<><button>Keep focus</button><ToastHost /></>);
    const button = screen.getByRole("button", { name: "Keep focus" }); button.focus();
    act(() => { toast("Saved."); vi.advanceTimersByTime(50); });
    act(() => { vi.advanceTimersByTime(50); });
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
    expect(button).toHaveFocus();
    act(() => { toast("Saved."); });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    act(() => { vi.advanceTimersByTime(50); });
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
  });
  it("announces a failed undo even when a newer notification exists", async () => {
    let id = 0; render(<ToastHost />);
    act(() => {
      id = toast("Archived", { undo: async () => { throw new Error("Permission changed"); } });
      toast("Another item saved.");
    });
    act(() => { vi.advanceTimersByTime(50); });
    await act(async () => { await undoToast(id); });
    act(() => { vi.advanceTimersByTime(50); });
    expect(screen.getByRole("status")).toHaveTextContent("Could not undo: Permission changed");
  });
  it("has accessible controls and a polite atomic live region", async () => {
    vi.useRealTimers();
    const { container } = render(<ToastHost />);
    act(() => { toast("Saved."); });
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("status")).toHaveAttribute("aria-atomic", "true");
    await expectNoA11yViolations(container);
  });
});
