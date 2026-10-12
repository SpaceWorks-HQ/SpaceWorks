import { useState, type RefObject } from "react";

/** Unsupported cameras simply omit torch; permission/capture flows stay usable. */
export function CameraTorch({ stream, ready }: { stream: RefObject<MediaStream | null>; ready: boolean }) {
  const [on, setOn] = useState(false);
  const [error, setError] = useState("");
  const track = ready ? stream.current?.getVideoTracks()[0] : undefined;
  let supported = false;
  try { supported = Boolean((track?.getCapabilities?.() as MediaTrackCapabilities & { torch?: boolean } | undefined)?.torch); }
  catch { /* Some cameras expose the method but refuse capability reads. */ }
  if (!supported) return null;
  return <><button className="desk-button min-h-11" type="button" aria-pressed={on} onClick={async () => {
    try { await track!.applyConstraints({ advanced: [{ torch: !on } as MediaTrackConstraintSet] }); setOn(!on); setError(""); }
    catch { setError("Torch unavailable. Continue scanning in better light."); }
  }}>{on ? "Turn torch off" : "Turn torch on"}</button>{error ? <p role="status">{error}</p> : null}</>;
}
