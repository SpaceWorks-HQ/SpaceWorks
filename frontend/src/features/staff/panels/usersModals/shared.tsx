export function ModalActions({
  pending,
  disabled,
  submitLabel = "Save",
  onClose,
  onSubmit,
}: {
  pending: boolean;
  disabled: boolean;
  submitLabel?: string;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="desk-actions flex flex-wrap justify-end gap-2">
      <button className="desk-button-ghost" type="button" disabled={pending} onClick={onClose}>Cancel</button>
      <button className="desk-button-primary" type="button" disabled={disabled} onClick={onSubmit}>{submitLabel}</button>
    </div>
  );
}

export function GeneralError({ error, errors }: { error: unknown; errors: Record<string, string> }) {
  const message = error instanceof Error ? error.message : "";
  if (!message || Object.keys(errors).length) return null;
  return <p className="text-sm text-danger">{message}</p>;
}

export function validationErrors(error: unknown) {
  if (!error || !(error instanceof Error)) return {};
  try {
    const parsed = JSON.parse(error.message) as Record<string, unknown>;
    return flattenErrors(parsed);
  } catch {
    return {};
  }
}

function flattenErrors(value: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      Array.isArray(item) ? item.join(" ") : typeof item === "string" ? item : JSON.stringify(item),
    ]),
  );
}
