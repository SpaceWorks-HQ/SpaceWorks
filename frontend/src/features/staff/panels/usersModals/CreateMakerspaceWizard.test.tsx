import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CreateMakerspaceModal } from "./CreateMakerspaceModal";
import { makerspacePayload } from "../users/forms";
import type { MakerspaceForm } from "./types";
import { expectNoA11yViolations } from "../../../../test/axe";
vi.mock("../../SpacePackProfilePicker", () => ({ SpacePackProfilePicker: ({ onChange }: { onChange: (profile: { id: number }) => void }) => <button type="button" onClick={() => onChange({ id: 7 })}>Choose pack</button> }));
it("collects identity, profile, hours, pack/modules and first staff, then submits once", async () => {
  const submit = vi.fn();
  function Harness() {
    const [form, setForm] = useState<MakerspaceForm>({ name: "Forge", public_code: "FRGE", slug: "forge", location: "Lab", superadmin_access_enabled: true });
    return <CreateMakerspaceModal open form={form} pending={false} error={null} onChange={setForm} onClose={vi.fn()} onSubmit={() => submit(makerspacePayload(form))} />;
  }
  const { container } = render(<Harness />);
  fireEvent.click(screen.getByText("Next"));
  fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: "Asia/Kolkata" } });
  fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "inr" } });
  fireEvent.click(screen.getByText("Next")); fireEvent.click(screen.getByText("Choose pack"));
  fireEvent.click(screen.getByLabelText(/Choose module families/)); fireEvent.click(screen.getByLabelText("Events"));
  fireEvent.click(screen.getByText("Next")); fireEvent.change(screen.getByLabelText("First staff email"), { target: { value: "desk@example.test" } });
  fireEvent.click(screen.getByText("Next")); expect(submit).not.toHaveBeenCalled();
  await expectNoA11yViolations(container);
  fireEvent.click(screen.getByRole("button", { name: "Create makerspace" }));
  expect(submit).toHaveBeenCalledTimes(1);
  expect(submit.mock.calls[0][0]).toMatchObject({ install_profile_id: 7, creation_setup: { profile: { timezone: "Asia/Kolkata", default_currency: "inr" }, modules: ["events"], first_staff_invite: { email: "desk@example.test", role_slug: "space_manager" } } });
  expect(submit.mock.calls[0][0].creation_setup.profile).toEqual({ timezone: "Asia/Kolkata", default_currency: "inr" });
});
it("refuses incomplete identity before advancing", () => {
  const submit = vi.fn();
  render(<CreateMakerspaceModal open form={{ name: "", public_code: "", slug: "", location: "", superadmin_access_enabled: true }} pending={false} error={null} onChange={vi.fn()} onClose={vi.fn()} onSubmit={submit} />);
  fireEvent.submit(screen.getByRole("button", { name: "Next" }).closest('[role="dialog"]')!.querySelector("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent("four-character public code"); expect(submit).not.toHaveBeenCalled();
});
