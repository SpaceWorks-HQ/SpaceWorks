import { StructuredApiError } from "../../lib/api";


export function evidenceErrorText(error: unknown) {
  if (error instanceof StructuredApiError && error.status === 410) {
    const expiredAt = error.body.object_expired_at;
    const when = typeof expiredAt === "string"
      ? new Date(expiredAt).toLocaleString()
      : "an unknown date";
    return `Photo expired on ${when} under retention policy.`;
  }
  return error instanceof Error ? error.message : "Could not load evidence photo.";
}
