import { beforeEach, expect, it, vi } from "vitest";
import { inboxUnreadKey, personalRecipientKey } from "./personalQueryKeys";
const { getAccessToken } = vi.hoisted(() => ({ getAccessToken: vi.fn() }));
vi.mock("../../lib/api", () => ({ getAccessToken }));
beforeEach(() => getAccessToken.mockReset());
function token(id: number, extra = "") { return `header.${btoa(JSON.stringify({ user_id: id, extra }))}.signature`; }
it("partitions recipient caches across accounts and keeps them stable across token refresh", () => {
  getAccessToken.mockReturnValue(token(1));
  const first = inboxUnreadKey(7);
  getAccessToken.mockReturnValue(token(1, "refresh"));
  expect(inboxUnreadKey(7)).toEqual(first);
  getAccessToken.mockReturnValue(token(2));
  expect(inboxUnreadKey(7)).not.toEqual(first);
  expect(personalRecipientKey()).toBe(2);
});
it("uses no token bytes in query keys and safely handles signed-out or malformed sessions", () => {
  getAccessToken.mockReturnValue(null);
  expect(personalRecipientKey()).toBe("signed-out");
  getAccessToken.mockReturnValue("malformed");
  expect(personalRecipientKey()).toBe("signed-out");
  getAccessToken.mockReturnValue(token(1));
  expect(inboxUnreadKey(7)).toEqual(["notifications-unread", 7, "staff", 1]);
});
