import { staffRequest } from "../../../lib/api";
import type {
  MachineAccessLevel,
  MachineCollection,
  MachineErrorLog,
  MachineOperator,
  MachineOperatorCandidate,
  MachineUsageEntry,
} from "./types";

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
