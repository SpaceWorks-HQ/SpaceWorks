import { staffRequest } from "../../lib/api";
import type { MachineTypePricing, MachineTypePricingList, MachineTypePricingSet } from "../../generated/api";
import { uploadPublicImage } from "./ImageUploader";

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

export const machineKeys = {
  all: ["machines"] as const,
  list: (makerspaceId: number) => ["machines", makerspaceId] as const,
  types: (makerspaceId: number) => ["machine-types", makerspaceId] as const,
  pricing: (makerspaceId: number) => ["machine-type-pricing", makerspaceId] as const,
  detail: (machineId: number) => ["machine", machineId] as const,
  usage: (machineId: number) => ["machine-usage", machineId] as const,
  operators: (machineId: number) => ["machine-operators", machineId] as const,
  operatorCandidates: (machineId: number) => ["machine-operator-candidates", machineId] as const,
  consumables: (machineId: number) => ["machine-consumables", machineId] as const,
  consumableCandidates: (machineId: number) => ["machine-consumable-candidates", machineId] as const,
  documents: (machineId: number) => ["machine-documents", machineId] as const,
  errors: (machineId: number) => ["machine-errors", machineId] as const,
};

export function collectionResults<T>(data: MachineCollection<T> | undefined): T[] {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results;
}

export const machinePublicPreviewKey = (machineId: number) =>
  ['machine-public-preview', machineId] as const;

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

export function getMachines(makerspaceId: number) {
  return staffRequest<MachineListResponse<Machine>>(`/admin/makerspace/${makerspaceId}/machines`);
}

export function createMachine(makerspaceId: number, payload: MachinePayload) {
  return staffRequest<Machine>(`/admin/makerspace/${makerspaceId}/machines`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function getMachineTypes(makerspaceId: number) {
  return staffRequest<MachineCollection<MachineType>>(`/admin/makerspace/${makerspaceId}/machine-types`);
}

export function createMachineType(
  makerspaceId: number,
  payload: Pick<MachineType, "slug" | "name" | "icon"> & { capability_config: MachineTypeCapabilityConfig },
) {
  return staffRequest<MachineType>(`/admin/makerspace/${makerspaceId}/machine-types`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function updateMachineType(
  makerspaceId: number,
  typeId: number,
  payload: Pick<MachineType, 'name' | 'icon'> & { capability_config: MachineTypeCapabilityConfig },
) {
  return staffRequest<MachineType>(`/admin/makerspace/${makerspaceId}/machine-types/${typeId}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  });
}

export function getMachineTypePricing(makerspaceId: number) {
  return staffRequest<MachineTypePricingList>(`/admin/makerspace/${makerspaceId}/machine-type-pricing`);
}

export function setMachineTypePricing(
  makerspaceId: number,
  machineTypeId: number,
  payload: MachineTypePricingSet,
) {
  return staffRequest<MachineTypePricing>(
    `/admin/makerspace/${makerspaceId}/machine-type-pricing/${machineTypeId}`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}
export function getMachine(machineId: number) {
  return staffRequest<Machine>(`/admin/machines/${machineId}`);
}

export function getMachinePublicPreview(machineId: number) {
  return staffRequest<MachinePublicPreview>(`/admin/machines/${machineId}/publicity`);
}

export function setMachinePublicity(machineId: number, is_public: boolean) {
  return staffRequest<MachinePublicPreview>(`/admin/machines/${machineId}/publicity`, {
    method: 'PATCH', body: JSON.stringify({ is_public }),
  });
}

export function updateMachine(machineId: number, payload: MachinePatch) {
  return staffRequest<Machine>(`/admin/machines/${machineId}`, {
    method: "PATCH", body: JSON.stringify(payload),
  });
}

export function machineImageEndpoint(machineId: number) {
  return `/admin/machines/${machineId}/image`;
}

export function uploadMachineImage(machineId: number, file: File) {
  return uploadPublicImage(machineImageEndpoint(machineId), file);
}

export function deleteMachineImage(machineId: number) {
  return staffRequest<Machine>(machineImageEndpoint(machineId), { method: "DELETE" });
}

export function setMachineStatus(machineId: number, status: MachineStatus) {
  return staffRequest<Machine>(`/admin/machines/${machineId}/set-status`, {
    method: "POST", body: JSON.stringify({ status }),
  });
}

export function retireMachine(machineId: number) {
  return staffRequest<Machine>(`/admin/machines/${machineId}/retire`, {
    method: "POST", body: JSON.stringify({}),
  });
}

export function unretireMachine(machineId: number) {
  return staffRequest<Machine>(`/admin/machines/${machineId}/unretire`, {
    method: "POST", body: JSON.stringify({}),
  });
}

export function getMachineUsage(machineId: number) {
  return staffRequest<MachineCollection<MachineUsageEntry>>(`/admin/machines/${machineId}/usage`);
}

export function addMachineUsage(machineId: number, payload: { hours: string; note: string }) {
  return staffRequest<MachineUsageEntry>(`/admin/machines/${machineId}/usage`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function getMachineOperators(machineId: number) {
  return staffRequest<MachineCollection<MachineOperator>>(`/admin/machines/${machineId}/operators`);
}

export function getOperatorCandidates(machineId: number) {
  return staffRequest<MachineOperatorCandidate[]>(`/admin/machines/${machineId}/operator-candidates`);
}

export function addMachineOperator(machineId: number, payload: { user_id: number; access_level: MachineAccessLevel }) {
  return staffRequest<MachineOperator>(`/admin/machines/${machineId}/operators`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export function updateMachineOperator(machineId: number, userPk: number, accessLevel: MachineAccessLevel) {
  return staffRequest<MachineOperator>(`/admin/machines/${machineId}/operators/${userPk}`, {
    method: "PATCH", body: JSON.stringify({ access_level: accessLevel }),
  });
}

export function deleteMachineOperator(machineId: number, userPk: number) {
  return staffRequest<void>(`/admin/machines/${machineId}/operators/${userPk}`, { method: "DELETE" });
}

export function getMachineErrorLogs(machineId: number) {
  return staffRequest<MachineCollection<MachineErrorLog>>(`/admin/machines/${machineId}/error-logs`);
}

export function addMachineErrorLog(machineId: number, payload: { severity: string; message: string }) {
  return staffRequest<MachineErrorLog>(`/admin/machines/${machineId}/error-logs`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

export {
  getConsumableCandidates,
  getMachineConsumables,
  linkMachineConsumable,
  logMachineConsumption,
  unlinkMachineConsumable,
  type ConsumableCandidate,
  type ConsumableMeasurement,
  type LinkConsumablePayload,
  type MachineConsumable,
} from "./machineConsumablesApi";

export {
  deleteMachineDocument,
  getMachineDocuments,
  getMachineDocumentUrl,
  uploadMachineDocument,
} from './machineDocumentsApi';
