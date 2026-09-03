export type TenantBootstrap = {
  makerspace: {
    id: number;
    name: string;
    slug: string;
    public_code: string;
    location: string;
    map_url?: string;
    logo_url?: string | null;
    cover_image_url?: string | null;
    geofence_enabled: boolean;
    public_stats_enabled?: boolean;
    membership_policy: "request" | "open" | "invite_only";
    // Present only when the makerspace opted into account-less borrow requests. Absent
    // means an account is required -- the backend omits the key otherwise to keep the
    // bootstrap payload byte-for-byte unchanged for everyone else.
    request_access?: "anyone";
  };
  frontend: {
    type: string;
    hostname: string;
    allowed_origins: string[];
  };
  modules: string[];
  features: string[];
  workflows: string[];
  theme: Record<string, string>;
  branding: Record<string, string>;
  email_enabled: boolean;
  public_api: {
    base_url: string;
    publishable_key: string;
    inventory_path: string;
  };
};

export type StaffAuthUser = {
  username: string;
  email_verified: boolean;
  role: string;
  is_superuser: boolean;
  must_change_password: boolean;
  makerspaces: {
    id: number;
    slug: string;
    role: string | null;
    role_id: number | null;
    role_name: string;
    role_slug: string | null;
    source: "membership" | "organization";
    actions: string[];
    can_configure_machine_types: boolean;
    is_machine_only: boolean;
    can_refer: boolean;
    can_verify: boolean;
    verified_at: string | null;
    referrals_enabled: boolean;
  }[];
};

export type PasswordLoginRequestedSurface = "member" | "staff";
export type PasswordLoginSurface = PasswordLoginRequestedSurface | "verification_only";
export type PasswordLoginRequest = {
  username: string;
  password: string;
  surface: PasswordLoginRequestedSurface;
};
export type PasswordLoginResponse<TUser = unknown> = {
  access: string;
  surface: PasswordLoginSurface;
  user: TUser;
};
