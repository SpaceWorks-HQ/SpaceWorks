export type ApiErrorBody = Record<string, unknown> & {
  detail?: unknown;
  code?: unknown;
};

export class StructuredApiError extends Error {
  readonly status: number;
  readonly detail?: string;
  readonly code?: string;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    const flattenMessages = (value: unknown): string[] => {
      if (typeof value === "string") return value.trim() ? [value.trim()] : [];
      if (Array.isArray(value)) return value.flatMap(flattenMessages);
      if (value && typeof value === "object") return Object.values(value).flatMap(flattenMessages);
      return [];
    };
    const detail = typeof body.detail === "string" ? body.detail.trim() : "";
    super(detail || Object.values(body).flatMap(flattenMessages).join(" ") || `Request failed (${status})`);
    this.name = "StructuredApiError";
    this.status = status;
    this.detail = detail || undefined;
    this.code = typeof body.code === "string" ? body.code : undefined;
    this.body = body;
  }
}

export function apiError(status: number, value: unknown) {
  const body = value && typeof value === "object" && !Array.isArray(value)
    ? value as ApiErrorBody
    : {};
  return new StructuredApiError(status, body);
}

export function messageForStatus(status: number): string {
  if (status === 401) {
    return "Inventory client is not authorized";
  }

  if (status === 404) {
    return "Makerspace not found";
  }

  if (status >= 500) {
    return "Inventory service is unavailable";
  }

  return "Unable to load inventory";
}
