import type React from "react";
import { useQuery } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";

export type Makerspace = {
  id: number;
  name: string;
  default_loan_days?: number;
  public_inventory_enabled?: boolean;
  public_code: string;
  slug: string;
  location?: string;
  geofence_latitude?: string | number | null;
  geofence_longitude?: string | number | null;
  geofence_radius_m?: number;
  geofence_enabled?: boolean;
  map_url?: string;
  telegram_group_chat_id: string;
  frontend_domain: string | null;
  frontend_domain_status?: "pending" | "verified" | "failed";
  domain_verified_at?: string | null;
  domain_verification_token?: string;
  domain_verification_record?: { host: string; type: "TXT"; value: string } | null;
  platform_hosting?: boolean;
  is_platform_subdomain?: boolean;
  hidden_from_central_directory: boolean;
  superadmin_access_enabled?: boolean;
  staff_notifications_enabled?: boolean;
  booking_requester_notifications_enabled?: boolean;
  public_stats_enabled?: boolean;
  public_print_status_lookup_policy?: "token_only" | "email_unverified";
  membership_policy?: "request" | "open" | "invite_only";
  membership_dues_amount?: string;
  referrals_enabled?: boolean;
  filament_low_stock_threshold_grams?: string | number;
  logo_url?: string | null;
  cover_image_url?: string | null;
  enabled_modules?: string[];
  enabled_features?: string[];
  // Separable apps this deployment does not ship. Empty unless TOMBSTONED_APPS is set,
  // and only meaningful for tabs no module key describes (see TAB_APPS in staffTabs).
  unavailable_apps?: string[];
  resource_limit_overrides?: Record<string, unknown>;
  branding_config?: {
    display_name?: string;
    support_email?: string;
    support_url?: string;
  } | null;
};

export type Product = {
  id: number;
  name: string;
  category: number | null;
  total_quantity: number;
  available_quantity: number;
  issued_quantity: number;
  damaged_quantity: number;
  lost_quantity: number;
  box?: number | null;
  description: string;
  tracking_mode: string;
  is_public: boolean;
  public_self_checkout_enabled: boolean;
  is_archived?: boolean;
  image_url?: string | null;
};

export type Category = {
  id: number;
  makerspace: number;
  name: string;
  slug: string;
  display_order: number;
  icon: string;
  product_count: number;
  created_at: string;
  updated_at: string;
};

export type CategoryListResponse = Category[] | { results: Category[] };

export function useStaffGet<T>(key: unknown[], path: string, enabled = true) {
  return useQuery({
    queryKey: key,
    queryFn: () => staffRequest<T>(path),
    enabled,
  });
}

export function categoryResults(data?: CategoryListResponse) {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results;
}

export function JsonRows({ data }: { data: unknown[] }) {
  if (!data.length) return <p className="mt-3 text-sm text-muted">No records.</p>;
  return <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-line bg-bg p-3 text-xs text-muted">{JSON.stringify(data, null, 2)}</pre>;
}

export function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="desk-panel overflow-hidden">
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-muted">{title}</h2>
      </div>
      <div className="desk-panel-body min-w-0 p-4">
        {children}
      </div>
    </section>
  );
}
