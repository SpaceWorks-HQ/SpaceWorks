import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { memberRequest, memberRequestBlob } from "../../../lib/api";
import type { MemberCard } from "../../staff/panels/memberCards/types";

export type { MemberCard };

type PhotoPresign = {
  object_key: string;
  content_type: string;
  url: string;
  fields?: Record<string, string>;
  method?: string;
  headers?: Record<string, string>;
};

export const memberCardKey = (makerspaceId: number) =>
  ["member", "member-card", makerspaceId] as const;

const cardPath = (makerspaceId: number) => `/member/makerspaces/${makerspaceId}/member-card`;

export function useMyMemberCard(makerspaceId: number) {
  return useQuery({
    queryKey: memberCardKey(makerspaceId),
    queryFn: () => memberRequest<MemberCard>(cardPath(makerspaceId)),
    // A member with no card issued yet gets a 404; retrying it just delays the empty state.
    retry: false,
  });
}

export function useRenameCard(makerspaceId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (printedName: string) =>
      memberRequest<MemberCard>(cardPath(makerspaceId), {
        method: "PATCH",
        body: JSON.stringify({ printed_name: printedName }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: memberCardKey(makerspaceId) }),
  });
}

/** Presign, upload to object storage, then attach — the same two-step flow the evidence
 *  uploader uses. The bucket write carries NO auth header, and the multipart POST must not
 *  set Content-Type so the browser adds its own boundary.
 *
 *  `consent` is required by the caller before this runs: the finalize PUT is what records
 *  the member's agreement to storing their photo, so it cannot be sent speculatively.
 */
export async function uploadCardPhoto(makerspaceId: number, file: File) {
  const presigned = await memberRequest<PhotoPresign>(`${cardPath(makerspaceId)}/photo`, {
    method: "POST",
    body: JSON.stringify({ content_type: file.type || "application/octet-stream" }),
  });

  if (presigned.method === "PUT") {
    const upload = await fetch(presigned.url, {
      method: "PUT",
      body: file,
      headers: presigned.headers,
    });
    if (!upload.ok) throw new Error(`Storage upload failed (${upload.status})`);
  } else {
    const formData = new FormData();
    Object.entries(presigned.fields ?? {}).forEach(([key, value]) => formData.append(key, value));
    formData.append("file", file);
    const upload = await fetch(presigned.url, { method: "POST", body: formData });
    if (!upload.ok) throw new Error(`Storage upload failed (${upload.status})`);
  }

  await memberRequest(`${cardPath(makerspaceId)}/photo`, {
    method: "PUT",
    body: JSON.stringify({
      object_key: presigned.object_key,
      content_type: presigned.content_type,
      consent: true,
    }),
  });
}

export function useDeleteCardPhoto(makerspaceId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => memberRequest<void>(`${cardPath(makerspaceId)}/photo`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: memberCardKey(makerspaceId) }),
  });
}

/** The watermarked preview. Opened as an object URL in a new tab because `<a href>`
 *  cannot carry the member's Authorization header. */
export function useCardPreview(makerspaceId: number) {
  return useMutation({
    mutationFn: async () => {
      const blob = await memberRequestBlob(`${cardPath(makerspaceId)}/preview.pdf`);
      window.open(URL.createObjectURL(blob), "_blank", "noopener");
    },
  });
}
