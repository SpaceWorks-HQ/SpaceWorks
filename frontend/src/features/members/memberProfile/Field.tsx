export function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-3">
      <label className="eyebrow block" htmlFor={id}>
        {label}
        {hint ? <span className="ml-2 normal-case tracking-normal text-muted">{hint}</span> : null}
      </label>
      {children}
    </div>
  );
}
