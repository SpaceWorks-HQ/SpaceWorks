import { API_V1_URL } from "../../lib/api";
import type { PasswordLoginResponse, StaffAuthUser } from "../../lib/api";

export type MfaChallenge = {
  mfa_required: true;
  enrollment_required: boolean;
  challenge: string;
  expires_in: number;
};
export type MfaCompleted = PasswordLoginResponse<StaffAuthUser> & { recovery_codes?: string[] };
export type Enrollment = { secret: string; provisioning_uri: string; qr_data_url: string };
export function isMfaChallenge(value: unknown): value is MfaChallenge {
  return typeof value === "object" && value !== null && "mfa_required" in value && value.mfa_required === true;
}

// A challenge never travels as a full account Authorization header, and must never
// trigger the shared client's refresh retry when a verification attempt gets a 401.
export async function mfaRequest<T>(path: string, body: object): Promise<T> {
  const response = await fetch(`${API_V1_URL}${path}`, {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to verify. Try again.");
  return data as T;
}
