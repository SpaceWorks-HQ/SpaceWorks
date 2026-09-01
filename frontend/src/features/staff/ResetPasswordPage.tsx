import { useSearchParams } from "react-router-dom";

import { LegacyPasswordResetForm } from "../auth/LegacyPasswordResetForm";
import { PasswordRecoveryFlow } from "../auth/PasswordRecoveryFlow";

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const hasLegacyLink = searchParams.has("uid") && searchParams.has("token");

  // Remove this branch only after the last legacy link issuance time plus
  // PASSWORD_RESET_TIMEOUT; release count is not a safe coexistence clock.
  if (hasLegacyLink) {
    return (
      <LegacyPasswordResetForm
        uid={searchParams.get("uid") ?? ""}
        token={searchParams.get("token") ?? ""}
      />
    );
  }

  return <PasswordRecoveryFlow />;
}
