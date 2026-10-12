import { staffRequest } from "../../../lib/api";
import { uploadPublicImage } from "../ImageUploader";
import type {
  Machine,
  MachineListResponse,
  MachinePatch,
  MachinePayload,
  MachinePublicPreview,
  MachineStatus,
} from "./types";

// Hard stop on the page walk below. The backend pages at 200 with a 500 maximum, so 50
// pages is 10,000 machines -- far past any real fleet. It exists so a server that always
// returns a `next` cannot spin this loop forever.
const MAX_MACHINE_PAGES = 50;

export async function getMachines(makerspaceId: number) {
  // EVERY page, not just the first. The console now states a machine COUNT and a status
  // roll-up per machine type, and a truncated list turns those from "a long list, cut off"
  // into a wrong number presented as fact.
  //
  // Paged with an explicit `?page=N` rather than by following DRF's `next`: `next` is an
  // ABSOLUTE url, while `staffRequest` prefixes everything it is given with the API base --
  // handing it straight over builds a malformed request.
  const first = await staffRequest<MachineListResponse<Machine>>(
    `/admin/makerspace/${makerspaceId}/machines`,
  );
  const results = [...first.results];
  let next = first.next;
  for (let page = 2; next && page <= MAX_MACHINE_PAGES; page += 1) {
    const response = await staffRequest<MachineListResponse<Machine>>(
      `/admin/makerspace/${makerspaceId}/machines?page=${page}`,
    );
    results.push(...response.results);
    next = response.next;
  }
  return { ...first, results };
}

export function createMachine(makerspaceId: number, payload: MachinePayload) {
  return staffRequest<Machine>(`/admin/makerspace/${makerspaceId}/machines`, {
    method: "POST", body: JSON.stringify(payload),
  });
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
