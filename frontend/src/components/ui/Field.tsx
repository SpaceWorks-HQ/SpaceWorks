import { cloneElement, isValidElement, type ReactNode } from "react";

export function Field({
  label,
  hint,
  error,
  className = "",
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  className?: string;
  children: ReactNode;
}) {
  const field = error !== undefined && isValidElement<{ "aria-invalid"?: boolean }>(children)
    ? cloneElement(children, { "aria-invalid": Boolean(error) })
    : children;

  return (
    <label className={`grid gap-1 ${className}`}>
      <span className="eyebrow">{label}</span>
      {field}
      {hint ? <span className="text-xs font-normal text-muted">{hint}</span> : null}
      {error ? <span className="text-xs font-normal text-danger">{error}</span> : null}
    </label>
  );
}
