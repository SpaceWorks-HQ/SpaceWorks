import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { NewPasswordFields } from "./NewPasswordFields";
import {
  CONFIRM_FAILURE_MESSAGE,
  RESEND_COOLDOWN_SECONDS,
  confirmOtpPasswordReset,
  isRecoveryUnavailable,
  requestPasswordReset,
} from "./passwordRecovery";

type RecoveryStep = "request" | "confirm" | "success" | "unavailable";

export function PasswordRecoveryFlow() {
  const [step, setStep] = useState<RecoveryStep>("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [acknowledgement, setAcknowledgement] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldown > 0]);

  const requestCode = async (isResend: boolean) => {
    setPending(true);
    setError("");
    try {
      const result = await requestPasswordReset({ email });
      setAcknowledgement(result.detail);
      setCooldown(RESEND_COOLDOWN_SECONDS);
      if (!isResend) setStep("confirm");
    } catch (requestError) {
      if (isRecoveryUnavailable(requestError)) {
        setStep("unavailable");
      } else {
        setError("Unable to request password recovery. Please try again.");
      }
    } finally {
      setPending(false);
    }
  };

  const submitConfirmation = async () => {
    setPending(true);
    setError("");
    try {
      await confirmOtpPasswordReset({ email, code, new_password: newPassword });
      setStep("success");
    } catch {
      // All server rejections intentionally share one message. Showing password-policy
      // details only after a valid OTP would recreate an account-existence oracle.
      setError(CONFIRM_FAILURE_MESSAGE);
    } finally {
      setPending(false);
    }
  };

  const canConfirm = /^\d{6}$/.test(code)
    && newPassword.length >= 8
    && newPassword === confirmPassword
    && !pending;

  return (
    <main className="desk-shell grid place-items-center px-5">
      <section className="desk-panel w-full max-w-md p-6">
        <SpaceWorksBadge className="mb-5" />
        <p className="text-xs font-semibold tracking-wide text-accent-ink">Account access</p>

        {step === "unavailable" ? (
          <>
            <h1 className="mt-2 text-2xl font-bold text-ink">Password recovery unavailable</h1>
            <p className="mt-4 text-sm text-muted" role="alert">
              Password recovery is unavailable on this deployment — contact your makerspace staff
            </p>
            <Link className="desk-button-ghost mt-5 w-full" to="/admin">Back to sign in</Link>
          </>
        ) : null}

        {step === "request" ? (
          <form onSubmit={(event) => { event.preventDefault(); void requestCode(false); }}>
            <h1 className="mt-2 text-2xl font-bold text-ink">Reset password</h1>
            <p className="mt-2 text-sm text-muted">
              Enter your account email to request a six-digit recovery code.
            </p>
            <label className="mt-5 block text-sm font-semibold" htmlFor="recovery-email">Email</label>
            <input
              id="recovery-email"
              className="desk-input mt-1 w-full"
              name="email"
              autoComplete="email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
            <button className="desk-button-secondary mt-5 w-full" type="submit" disabled={pending}>
              {pending ? "Requesting..." : "Request recovery code"}
            </button>
            <Link className="desk-button-ghost mt-3 w-full" to="/admin">Back to sign in</Link>
          </form>
        ) : null}

        {step === "confirm" ? (
          <form onSubmit={(event) => { event.preventDefault(); if (canConfirm) void submitConfirmation(); }}>
            <h1 className="mt-2 text-2xl font-bold text-ink">Enter your recovery code</h1>
            <p className="mt-2 text-sm text-muted">{acknowledgement}</p>
            <p className="mt-2 text-sm text-muted">
              Email delivery runs on a schedule and may take a few minutes.
            </p>
            <label className="mt-5 block text-sm font-semibold" htmlFor="recovery-code">
              Six-digit code
            </label>
            <input
              id="recovery-code"
              className="desk-input mt-1 w-full"
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
            />
            <NewPasswordFields
              idPrefix="otp-reset"
              newPassword={newPassword}
              confirmPassword={confirmPassword}
              onNewPasswordChange={setNewPassword}
              onConfirmPasswordChange={setConfirmPassword}
            />
            {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
            <button className="desk-button-secondary mt-5 w-full" type="submit" disabled={!canConfirm}>
              {pending ? "Updating..." : "Update password"}
            </button>
            <button
              className="desk-button-ghost mt-3 w-full"
              type="button"
              disabled={pending || cooldown > 0}
              onClick={() => void requestCode(true)}
            >
              {cooldown > 0 ? `Request another code in ${cooldown}s` : "Request another code"}
            </button>
          </form>
        ) : null}

        {step === "success" ? (
          <>
            <h1 className="mt-2 text-2xl font-bold text-ink">Password updated</h1>
            <p className="mt-4 text-sm text-muted">Your password has been updated. You can now sign in.</p>
            <Link className="desk-button-secondary mt-5 w-full" to="/admin">Go to sign in</Link>
          </>
        ) : null}
      </section>
    </main>
  );
}
