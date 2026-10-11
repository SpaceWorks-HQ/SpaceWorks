import { afterEach, expect, it } from "vitest";
import { clearAccessToken, setAccessToken } from "./api/client";
import { toast, toastStore } from "../components/ui/toastStore";

const token = (user_id: number) => `header.${btoa(JSON.stringify({ user_id }))}.signature`;
afterEach(() => { clearAccessToken(); localStorage.clear(); });
it("retains undo during a token refresh but clears it on account change and sign-out", () => {
  setAccessToken(token(1));
  toast("Private drill archived", { undo: async () => {} });
  setAccessToken(token(1));
  expect(toastStore.snapshot()).toHaveLength(1);
  setAccessToken(token(2));
  expect(toastStore.snapshot()).toHaveLength(0);
  toast("Another item archived");
  clearAccessToken();
  expect(toastStore.snapshot()).toHaveLength(0);
});
