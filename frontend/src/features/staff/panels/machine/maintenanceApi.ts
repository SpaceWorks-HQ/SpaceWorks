import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../../lib/api";
import { machineKeys } from "../../machinesApi";

export type MaintenanceDocument = {
  id: number;
  log_id: number;
  object_key: string;
  size_bytes: number;
  uploaded_by_id: number | null;
  created_at: string;
};
export type MaintenanceSchedule = {
  id: number;
  machine_id: number;
  description: string;
  interval_days: number;
  anchor?: "completion" | "calendar";
  next_due: string;
  is_active: boolean;
  created_by_id: number | null;
  created_at: string;
  updated_at: string;
  overdue: boolean;
};
export type MaintenanceLog = {
  id: number;
  machine_id: number;
  performed_by_id: number | null;
  performed_at: string;
  summary: string;
  cost: string | null;
  parts_note: string;
  created_at: string;
  documents: MaintenanceDocument[];
};
export type MaintenancePage<T> = {
  count: number;
  next?: string | null;
  previous?: string | null;
  results: T[];
};
export type ScheduleInput = {
  description: string;
  interval_days: number;
  anchor?: "completion" | "calendar";
  next_due: string;
};
export type LogInput = {
  summary: string;
  performed_at?: string;
  cost?: string | null;
  parts_note?: string;
  set_idle?: boolean;
  schedule_id?: number;
};
export type UploadContract = {
  object_key: string;
  upload: {
    url: string;
    method?: string;
    fields?: Record<string, string>;
    headers?: Record<string, string>;
  };
};

export const maintenanceKeys = {
  schedules: (machineId: number) => ["maintenance", "schedules", machineId] as const,
  logs: (machineId: number) => ["maintenance", "logs", machineId] as const,
  logDocuments: (logId: number) => ["maintenance", "documents", logId] as const,
};

const schedulePath = (makerspaceId: number, machineId: number) =>
  `/admin/makerspaces/${makerspaceId}/machines/${machineId}/maintenance/schedules/`;
const logPath = (makerspaceId: number, machineId: number) =>
  `/admin/makerspaces/${makerspaceId}/machines/${machineId}/maintenance/logs/`;

export function useMaintenanceSchedules(
  makerspaceId: number, machineId: number, enabled: boolean,
) {
  return useQuery({
    queryKey: maintenanceKeys.schedules(machineId),
    queryFn: () => staffRequest<MaintenancePage<MaintenanceSchedule>>(
      schedulePath(makerspaceId, machineId),
    ),
    enabled,
  });
}

export function useMaintenanceLogs(
  makerspaceId: number, machineId: number, enabled: boolean,
) {
  return useQuery({
    queryKey: maintenanceKeys.logs(machineId),
    queryFn: () => staffRequest<MaintenancePage<MaintenanceLog>>(
      logPath(makerspaceId, machineId),
    ),
    enabled,
  });
}

function useScheduleInvalidation(makerspaceId: number, machineId: number) {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: maintenanceKeys.schedules(machineId) }),
      client.invalidateQueries({ queryKey: ["dashboard", makerspaceId] }),
    ]);
  };
}

export function useCreateMaintenanceSchedule(makerspaceId: number, machineId: number) {
  const invalidate = useScheduleInvalidation(makerspaceId, machineId);
  return useMutation({
    mutationFn: (input: ScheduleInput) =>
      staffRequest<MaintenanceSchedule>(schedulePath(makerspaceId, machineId), {
        method: "POST", body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useUpdateMaintenanceSchedule(makerspaceId: number, machineId: number) {
  const invalidate = useScheduleInvalidation(makerspaceId, machineId);
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: Partial<ScheduleInput> }) =>
      staffRequest<MaintenanceSchedule>(`/admin/maintenance/schedules/${id}/`, {
        method: "PATCH", body: JSON.stringify(input),
      }),
    onSuccess: invalidate,
  });
}

export function useDeactivateMaintenanceSchedule(makerspaceId: number, machineId: number) {
  const invalidate = useScheduleInvalidation(makerspaceId, machineId);
  return useMutation({
    mutationFn: (id: number) =>
      staffRequest<MaintenanceSchedule>(
        `/admin/maintenance/schedules/${id}/deactivate/`,
        { method: "POST", body: JSON.stringify({}) },
      ),
    onSuccess: invalidate,
  });
}

export function useLogMaintenance(makerspaceId: number, machineId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: LogInput) =>
      staffRequest<MaintenanceLog>(logPath(makerspaceId, machineId), {
        method: "POST", body: JSON.stringify(input),
      }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: maintenanceKeys.logs(machineId) }),
        client.invalidateQueries({ queryKey: maintenanceKeys.schedules(machineId) }),
        client.invalidateQueries({ queryKey: machineKeys.detail(machineId) }),
        client.invalidateQueries({ queryKey: machineKeys.all }),
        client.invalidateQueries({ queryKey: ["dashboard", makerspaceId] }),
      ]);
    },
  });
}

export function usePresignMaintenanceDocument(logId: number) {
  return useMutation({
    mutationFn: (file: File) => staffRequest<UploadContract>(
      `/admin/maintenance/logs/${logId}/documents/presign/`,
      {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || "application/octet-stream",
        }),
      },
    ),
  });
}

export function useFinalizeMaintenanceDocument(machineId: number, logId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (objectKey: string) => staffRequest<MaintenanceDocument>(
      `/admin/maintenance/logs/${logId}/documents/`,
      { method: "POST", body: JSON.stringify({ object_key: objectKey }) },
    ),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: maintenanceKeys.logs(machineId) }),
        client.invalidateQueries({ queryKey: maintenanceKeys.logDocuments(logId) }),
      ]);
    },
  });
}

export function useMaintenanceDocumentUrl() {
  return useMutation({
    mutationFn: (id: number) => staffRequest<{ url: string }>(
      `/admin/maintenance/log-documents/${id}/url/`,
    ),
    onSuccess: ({ url }) => window.open(url, "_blank", "noopener,noreferrer"),
  });
}

export function useDeleteMaintenanceDocument(machineId: number, logId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => staffRequest<void>(
      `/admin/maintenance/log-documents/${id}/`, { method: "DELETE" },
    ),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: maintenanceKeys.logs(machineId) }),
        client.invalidateQueries({ queryKey: maintenanceKeys.logDocuments(logId) }),
      ]);
    },
  });
}

export async function uploadToContract(file: File, contract: UploadContract) {
  if (contract.upload.method === "PUT") {
    const response = await fetch(contract.upload.url, {
      method: "PUT", body: file, headers: contract.upload.headers,
    });
    if (!response.ok) throw new Error(`Storage upload failed (${response.status})`);
    return;
  }
  const body = new FormData();
  Object.entries(contract.upload.fields ?? {}).forEach(([key, value]) => body.append(key, value));
  body.append("file", file);
  const response = await fetch(contract.upload.url, { method: "POST", body });
  if (!response.ok) throw new Error(`Storage upload failed (${response.status})`);
}
