import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";

type ChangePasswordGateProps = {
  username: string;
  onChanged: () => void;
  onSignOut: () => void;
};

// Shown after login when the account still carries must_change_password (the
// default super123 seed). It blocks the console until the password is rotated.
export function ChangePasswordGate({ username, onChanged, onSignOut }: ChangePasswordGateProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      staffRequest("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      }),
    onSuccess: onChanged,
  });
  const mismatch = confirm.length > 0 && newPassword !== confirm;
  const canSubmit =
    currentPassword.length > 0 && newPassword.length > 0 && !mismatch && !mutation.isPending;

  return (
    <main className="desk-shell grid place-items-center px-5">
      <form
        className="desk-panel w-full max-w-md p-6"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) mutation.mutate();
        }}
      >
        <input
          className="sr-only"
          type="text"
          autoComplete="username"
          value={username}
          readOnly
          tabIndex={-1}
          aria-hidden="true"
        />
        <SpaceWorksBadge className="mb-5" />
        <p className="text-xs font-semibold tracking-wide text-accent-ink">Security</p>
        <h1 className="mt-2 text-2xl font-bold text-ink">Set a new password</h1>
        <p className="mt-2 text-sm text-muted">
          The account <span className="font-semibold text-ink">{username}</span> is using a default
          password and must set a new one before continuing.
        </p>
        <label className="mt-5 block text-sm font-semibold" htmlFor="change-current-password">Current password</label>
        <input
          className="desk-input mt-1 w-full"
          type="password"
          id="change-current-password"
          autoComplete="current-password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
        />
        <label className="mt-3 block text-sm font-semibold" htmlFor="change-new-password">New password</label>
        <input
          className="desk-input mt-1 w-full"
          type="password"
          id="change-new-password"
          autoComplete="new-password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
        />
        <label className="mt-3 block text-sm font-semibold" htmlFor="change-confirm-password">Confirm new password</label>
        <input
          className="desk-input mt-1 w-full"
          type="password"
          id="change-confirm-password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {mismatch ? <p className="mt-3 text-sm text-danger">Passwords do not match.</p> : null}
        {mutation.error ? (
          <p className="mt-3 text-sm text-danger">{(mutation.error as Error).message}</p>
        ) : null}
        <button className="desk-button-primary mt-5 w-full" disabled={!canSubmit}>
          {mutation.isPending ? "Updating..." : "Update password"}
        </button>
        <button className="desk-button mt-2 w-full" type="button" onClick={onSignOut}>
          Sign out
        </button>
      </form>
    </main>
  );
}
