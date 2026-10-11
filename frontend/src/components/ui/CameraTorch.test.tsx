import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CameraTorch } from "./CameraTorch";

function stream(track: object) { return { current: { getVideoTracks: () => [track] } as unknown as MediaStream }; }
it("omits unsupported or refusing capability reads", () => {
  const { rerender } = render(<CameraTorch ready stream={stream({})} />);
  expect(screen.queryByRole("button")).toBeNull();
  rerender(<CameraTorch ready stream={stream({ getCapabilities: () => { throw new Error("Unsupported"); } })} />);
  expect(screen.queryByRole("button")).toBeNull();
});
it("toggles the camera torch and keeps scanning usable after a constraint failure", async () => {
  const applyConstraints = vi.fn().mockResolvedValue(undefined);
  render(<CameraTorch ready stream={stream({ getCapabilities: () => ({ torch: true }), applyConstraints })} />);
  fireEvent.click(screen.getByText("Turn torch on"));
  expect(await screen.findByText("Turn torch off")).toHaveAttribute("aria-pressed", "true");
  expect(applyConstraints).toHaveBeenCalledWith({ advanced: [{ torch: true }] });
  applyConstraints.mockRejectedValue(new Error("Device busy")); fireEvent.click(screen.getByText("Turn torch off"));
  expect(await screen.findByRole("status")).toHaveTextContent("Torch unavailable");
});
