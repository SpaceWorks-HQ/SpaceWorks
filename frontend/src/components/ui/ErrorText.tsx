export function ErrorText({ message }: { message?: string | null }) {
  if (!message) return null;
  return <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{message}</p>;
}
