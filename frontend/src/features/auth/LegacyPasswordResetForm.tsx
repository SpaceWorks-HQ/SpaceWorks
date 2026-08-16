import { useState } from "react";
import { Link } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { NewPasswordFields } from "./NewPasswordFields";
import { CONFIRM_FAILURE_MESSAGE, confirmLegacyPasswordReset } from "./passwordRecovery";

export function LegacyPasswordResetForm({ uid, token }: { uid: string; token: string }) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState(false);
  const canSubmit = newPassword.length >= 8
    && newPassword === confirmPassword
    && !pending;

  const submit = async () => {
    setPending(true);
    setError("");
    try {
      await confirmLegacyPasswordReset({ uid, token, new_password: newPassword });
      setUpdated(true);
    } catch {
      setError(CONFIRM_FAILURE_MESSAGE);
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="desk-shell grid place-items-center px-5">
      <section className="desk-panel w-full max-w-md p-6">
        <SpaceWorksBadge className="mb-5" />
        <p className="text-xs font-semibold tracking-wide text-accent-ink">Account access</p>
        {updated ? (
          <>
            <h1 className="mt-2 text-2xl font-bold text-ink">Password updated</h1>
            <p className="mt-4 text-sm text-muted">Your password has been updated. You can now sign in.</p>
            <Link className="desk-button-secondary mt-5 w-full" to="/admin">Go to sign in</Link>
          </>
        ) : (
          <form onSubmit={(event) => { event.preventDefault(); if (canSubmit) void submit(); }}>
            <h1 className="mt-2 text-2xl font-bold text-ink">Set a new password</h1>
            <NewPasswordFields
              idPrefix="legacy-reset"
              newPassword={newPassword}
              confirmPassword={confirmPassword}
              onNewPasswordChange={setNewPassword}
              onConfirmPasswordChange={setConfirmPassword}
            />
            {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
            <button className="desk-button-secondary mt-5 w-full" type="submit" disabled={!canSubmit}>
              {pending ? "Updating..." : "Update password"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
