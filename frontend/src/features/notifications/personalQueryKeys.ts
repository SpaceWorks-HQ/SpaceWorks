import { getAccessToken } from "../../lib/api";

// A cache partition only. The API verifies the JWT and owns authorization.
// Refreshing the same user's token keeps their cache; changing users changes keys.
export function personalRecipientKey(): number | "signed-out" {
  try {
    const token = getAccessToken();
    if (!token) return "signed-out";
    const segment = token.split(".")[1];
    const claims = JSON.parse(atob(segment.replace(/-/g, "+").replace(/_/g, "/"))) as { user_id?: unknown };
    return typeof claims.user_id === "number" && Number.isSafeInteger(claims.user_id) && claims.user_id > 0
      ? claims.user_id : "signed-out";
  } catch { return "signed-out"; }
}

export const inboxUnreadKey = (id: number | undefined, mode = "staff") =>
  ["notifications-unread", id, mode, personalRecipientKey()] as const;
