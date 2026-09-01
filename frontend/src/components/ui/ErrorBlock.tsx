export function ErrorBlock({ error, className = "" }: { error: unknown; className?: string }) {
  if (!(error instanceof Error)) return null;
  return <p className={`text-sm text-danger ${className}`.trim()} role="alert">{error.message}</p>;
}
