import { staffRequest } from "../../lib/api";

export type SpacePack = {
  format: "spaceworks-space-pack";
  version: number;
  configuration: Record<string, unknown>;
  checksum: string;
};
export type PackPreview = {
  base_checksum: string;
  applied: boolean;
  changes: { section: string; key: string; before: unknown; after: unknown }[];
};
export type PackProfile = { id: number; name: string; pack: SpacePack };
type ProfilePage = { count: number; next: string | null; previous: string | null; results: PackProfile[] };

export const exportSpacePack = (id: number) => staffRequest<SpacePack>(`/admin/makerspace/${id}/space-pack`);
export const importSpacePack = (id: number, pack: SpacePack, baseChecksum?: string) =>
  staffRequest<PackPreview>(`/admin/makerspace/${id}/space-pack`, {
    method: "POST", body: JSON.stringify({ pack, dry_run: !baseChecksum, ...(baseChecksum ? { base_checksum: baseChecksum } : {}) }),
  });
export const listPackProfiles = (page = 1) => staffRequest<ProfilePage>(`/admin/space-pack-profiles?page=${page}`);
export const savePackProfile = (name: string, pack: SpacePack) => staffRequest<PackProfile>("/admin/space-pack-profiles", {
  method: "POST", body: JSON.stringify({ name, pack }),
});
