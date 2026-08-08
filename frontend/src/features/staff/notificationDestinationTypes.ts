export type DestinationScope = {
  machine_type_ids: number[];
  machine_ids: number[];
  category_ids: number[];
};

export type NotificationDestination = {
  id: number;
  channel: "telegram" | "slack" | "mattermost" | "discord";
  label: string;
  telegram_chat_id: string;
  is_active: boolean;
  /** Whether a credential is stored. The credential itself is never returned. */
  credential_set: boolean;
  scope: DestinationScope;
  created_at: string;
  updated_at: string;
};

export type RecipientKind = "role" | "requester" | "members" | "user";

export type RecipientRule = {
  id: number;
  feature: string;
  event: string;
  kind: RecipientKind;
  role_id: number | null;
  user_id: number | null;
  scope: DestinationScope;
};

export type RecipientRulesResponse = {
  features: { key: string; events: string[] }[];
  roles: { id: number; name: string; slug: string }[];
  members: { id: number; username: string; email: string }[];
  rules: RecipientRule[];
};

export const EMPTY_SCOPE: DestinationScope = {
  machine_type_ids: [],
  machine_ids: [],
  category_ids: [],
};
