type Props = { branding?: Record<string, string> };

export function SupportContact({ branding }: Props) {
  const email = branding?.support_email;
  const emailSafe = typeof email === "string" && /^[^\s@?&#:]+@[^\s@?&#:]+\.[^\s@?&#:]+$/.test(email);
  let url: string | undefined;
  try {
    const parsed = new URL(branding?.support_url ?? "");
    if (["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password) url = parsed.href;
  } catch { /* Empty or legacy invalid URLs are not links. */ }
  if (!emailSafe && !url) return null;
  return <div className="flex flex-wrap items-center gap-3 text-sm text-muted" aria-label="Support contact">
    <span>Need help?</span>
    {emailSafe ? <a className="underline hover:text-ink" href={`mailto:${encodeURI(email)}`}>{email}</a> : null}
    {url ? <a className="underline hover:text-ink" href={url} target="_blank" rel="noreferrer">Contact support</a> : null}
  </div>;
}
