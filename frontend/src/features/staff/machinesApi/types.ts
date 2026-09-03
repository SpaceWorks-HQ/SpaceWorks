export type MachineStatus = "idle" | "running" | "reserved" | "maintenance" | "offline";
export type MachineAccessLevel = "operate" | "manage" | "full";
export type MachineWarrantyStatus = "unknown" | "active" | "expiring_soon" | "expired";

export type MachineType = {
  id: number;
  slug: string;
  name: string;
  icon: string;
  is_builtin: boolean;
  managing_action: string;
  makerspace: number | null;
  // Present only on the machine-type LIST response, which is the one serializer that
  // resolves it against an actor. The same type is nested inside machine rows, where
  // there is no actor context and the field is genuinely absent -- so it is optional,
  // and an absent value correctly reads as "no creation authority proven".
  can_create_machine?: boolean;
  capability_config?: MachineTypeCapabilityConfig;
};

export type MeteringUnit = "weight" | "volume" | "length" | "count" | "minutes";
export type MachineTypeCapabilityConfig = {
  metering_unit: MeteringUnit;
  requires_booking: boolean;
  accepted_materials?: string[];
  accepted_colours?: string[];
};

export type Machine = {
  id: number;
  makerspace: number;
  machine_type: MachineType;
  name: string;
  location: string;
  notes: string;
  status: MachineStatus;
  firmware_version: string;
  camera_feed_url: string;
  image_url: string | null;
  warranty_status: MachineWarrantyStatus;
  is_public: boolean;
  is_active: boolean;
  type_payload?: { model?: string };
  usage_hours: string;
  can_operate: boolean;
  can_edit: boolean;
  can_delegate: boolean;
  can_retire: boolean;
  can_unretire: boolean;
  can_manage: boolean;
  created_at: string;
  updated_at: string;
};

export type MachinePublicPreview = {
  name: string;
  machine_type: { name: string; icon: string };
  image_url: string | null;
  status: MachineStatus;
  usage_hours: string;
};

export type MachineOperator = {
  id: number;
  user: number;
  username: string;
  access_level: MachineAccessLevel;
  assigned_by_username: string | null;
  assigned_at: string;
};

export type MachineOperatorCandidate = {
  user_id: number;
  username: string;
  display_name: string;
};

export type MachineUsageEntry = {
  id: number;
  hours: string;
  source: string;
  note: string;
  logged_by_username: string | null;
  created_at: string;
};

export type MachineDocument = {
  id: number;
  doc_type: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
};

export type MachineErrorLog = {
  id: number;
  severity: string;
  message: string;
  logged_by_username: string | null;
  created_at: string;
};

export type MachineListResponse<T> = {
  count: number;
  next?: string | null;
  previous?: string | null;
  results: T[];
};
export type MachineCollection<T> = MachineListResponse<T> | T[];

export type MachinePayload = {
  name: string;
  location: string;
  notes: string;
  firmware_version: string;
  camera_feed_url: string;
  machine_type_id: number;
  type_payload?: { model?: string };
};
export type MachinePatch = Partial<MachinePayload> & { status?: MachineStatus };
