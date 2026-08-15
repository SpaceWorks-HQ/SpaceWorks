export function NewPasswordFields({
  idPrefix,
  newPassword,
  confirmPassword,
  onNewPasswordChange,
  onConfirmPasswordChange,
}: {
  idPrefix: string;
  newPassword: string;
  confirmPassword: string;
  onNewPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
}) {
  const tooShort = newPassword.length > 0 && newPassword.length < 8;
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;

  return (
    <>
      <label className="mt-3 block text-sm font-semibold" htmlFor={`${idPrefix}-password`}>
        New password
      </label>
      <input
        id={`${idPrefix}-password`}
        className="desk-input mt-1 w-full"
        type="password"
        autoComplete="new-password"
        value={newPassword}
        aria-describedby={tooShort ? `${idPrefix}-password-error` : undefined}
        aria-invalid={tooShort}
        onChange={(event) => onNewPasswordChange(event.target.value)}
      />
      {tooShort ? (
        <p
          id={`${idPrefix}-password-error`}
          className="mt-2 text-sm text-danger"
          role="alert"
        >
          Password must be at least 8 characters.
        </p>
      ) : null}

      <label className="mt-3 block text-sm font-semibold" htmlFor={`${idPrefix}-confirm`}>
        Confirm password
      </label>
      <input
        id={`${idPrefix}-confirm`}
        className="desk-input mt-1 w-full"
        type="password"
        autoComplete="new-password"
        value={confirmPassword}
        aria-describedby={mismatch ? `${idPrefix}-confirm-error` : undefined}
        aria-invalid={mismatch}
        onChange={(event) => onConfirmPasswordChange(event.target.value)}
      />
      {mismatch ? (
        <p
          id={`${idPrefix}-confirm-error`}
          className="mt-2 text-sm text-danger"
          role="alert"
        >
          Passwords do not match.
        </p>
      ) : null}
    </>
  );
}
