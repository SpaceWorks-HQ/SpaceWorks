import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { mfaRequest, type Enrollment, type MfaChallenge, type MfaCompleted } from "./mfaApi";

export function MfaFlow({ challenge, onComplete, onCancel }: {
  challenge: MfaChallenge;
  onComplete: (result: MfaCompleted) => void;
  onCancel: () => void;
}) {
  const [code, setCode] = useState("");
  const [enrollment, setEnrollment] = useState<Enrollment>();
  const [completed, setCompleted] = useState<MfaCompleted>();
  const enroll = useMutation({
    mutationFn: () => mfaRequest<Enrollment>("/auth/mfa/enroll", { challenge: challenge.challenge }),
    onSuccess: setEnrollment,
  });
  const verify = useMutation({
    mutationFn: () => mfaRequest<MfaCompleted>(challenge.enrollment_required ? "/auth/mfa/confirm" : "/auth/mfa/verify",
      { challenge: challenge.challenge, code }),
    onSuccess: (result) => result.recovery_codes ? setCompleted(result) : onComplete(result),
  });
  if (completed) return <section className="desk-panel mx-auto grid max-w-lg gap-4 p-6">
    <h1 className="text-2xl font-bold">Save your recovery codes</h1>
    <p>Each code works once. Save these somewhere secure; they will not be shown again.</p>
    <ul className="grid grid-cols-2 gap-2">{completed.recovery_codes?.map((value) => <li key={value}><code>{value}</code></li>)}</ul>
    <button type="button" className="desk-button-primary" onClick={() => onComplete(completed)}>I saved my codes. Continue</button>
  </section>;
  const error = enroll.error ?? verify.error;
  return <section className="desk-panel mx-auto grid max-w-lg gap-4 p-6">
    <h1 className="text-2xl font-bold">{challenge.enrollment_required ? "Set up two-step sign-in" : "Verify your sign-in"}</h1>
    <p>{challenge.enrollment_required ? "Add SpaceWorks to your authenticator app to secure this account." : "Enter the code from your authenticator app, or one of your recovery codes."}</p>
    {challenge.enrollment_required && !enrollment ? <button type="button" className="desk-button-primary" disabled={enroll.isPending} onClick={() => enroll.mutate()}>Show enrollment QR and key</button> : null}
    {enrollment ? <>
      <img src={enrollment.qr_data_url} alt="Scan to add SpaceWorks to your authenticator" className="w-56 bg-white" />
      <p>Manual key: <code className="break-all select-all">{enrollment.secret}</code></p>
    </> : null}
    {(!challenge.enrollment_required || enrollment) ? <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); verify.mutate(); }}>
      <label htmlFor="mfa-code">Authenticator{!challenge.enrollment_required ? " or recovery" : ""} code</label>
      <input id="mfa-code" className="desk-input" autoComplete="one-time-code" value={code} maxLength={64} required onChange={(event) => setCode(event.target.value)} />
      <button type="submit" className="desk-button-primary" disabled={verify.isPending}>Verify</button>
    </form> : null}
    {error ? <p role="alert" className="text-danger">{error.message}</p> : null}
    <p className="text-sm text-muted">This sign-in expires in {Math.ceil(challenge.expires_in / 60)} minutes. Restart sign-in if it expires.</p>
    <button type="button" className="desk-button" onClick={onCancel}>Back to sign-in</button>
  </section>;
}
