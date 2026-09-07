// Hand-written types for the member ID card surface. The generated client
// (src/generated/api.ts) is regenerated from the OpenAPI snapshot in a separate
// commit; these mirror the documented shapes until that lands.

export type MemberCard = {
  id: number;
  // A per-makerspace PositiveIntegerField on the backend, not a formatted string.
  card_number: number;
  printed_name: string;
  membership_id: number | null;
  is_active: boolean;
  photo_set: boolean;
  photo_consent_at: string | null;
  qr_active: boolean;
  print_count: number;
  last_printed_at: string | null;
  issued_at: string;
  revoked_at: string | null;
  revoked_reason: string;
  created_at: string;
  updated_at: string;
};

export type MemberCardPage = {
  count: number;
  next: string | null;
  previous: string | null;
  results: MemberCard[];
};

export type CardStatus = "active" | "revoked";

export const REISSUE_REASONS = ["lost", "stolen", "damaged", "renewed"] as const;
export type ReissueReason = (typeof REISSUE_REASONS)[number];

/** A scan lookup. Anything but `ok` carries no card detail worth rendering: a
 *  revoked or inactive card must read as refused, not as a member's identity. */
export type CardResolveResult = {
  outcome: "ok" | "revoked" | "inactive";
  card_id?: number;
  card_number?: number;
  printed_name?: string;
  membership_id?: number;
  membership_status?: string;
  photo_url?: string;
};

export const CARD_FRONT_FIELDS = [
  "printed_name",
  "card_number",
  "makerspace",
  "issued_at",
  "membership_role",
] as const;
export type CardFrontField = (typeof CARD_FRONT_FIELDS)[number];

export type CardTemplate = {
  version: number;
  page: "a4" | "letter" | "cr80";
  orientation: "portrait" | "landscape";
  card_width_mm: number;
  card_height_mm: number;
  margin_mm: number;
  gap_mm: number;
  front_fields: string[];
  back_text: string;
  include_photo: boolean;
  include_qr: boolean;
  name_font_size_pt: number;
  font_size_pt: number;
  crop_marks: boolean;
};

/** Only the fields the issue roster reads. The membership list is shared with the
 *  Users panel, which types more of it; `status` is optional so a backend that omits
 *  it renders a row rather than crashing the roster. */
export type CardMembershipRow = {
  id: number;
  user: { username: string; display_name?: string };
  status?: string;
};
