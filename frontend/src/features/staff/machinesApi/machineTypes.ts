import { staffRequest } from "../../../lib/api";
import type {
  MachineTypePricing,
  MachineTypePricingList,
  MachineTypePricingSet,
} from "../../../generated/api";
import type { MachineCollection, MachineType, MachineTypeCapabilityConfig } from "./types";

// Mirrors backend `printer_capabilities.is_printer_type`: the built-in printer is the GLOBAL
// type, not merely one slugged `3d_printer`. A makerspace may legally create a local type with
// that slug, and matching on the slug alone would mount the printer console for it -- applying
// printer-only fields to a generic service and querying the same slug from two sections, which
// duplicates and mixes their jobs.
export function isBuiltinPrinterType(machineType: Pick<MachineType, "slug" | "makerspace"> | undefined) {
  return !!machineType && machineType.makerspace === null && machineType.slug === "3d_printer";
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
