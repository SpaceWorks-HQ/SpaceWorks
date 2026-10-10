/** Display the configured price with the host's currency on public catalogues. */
export function EventPrice({ amount, currency }: { amount: string; currency: string }) {
  return <div><dt className="eyebrow">Price</dt><dd className="font-mono font-semibold text-ink">
    {Number(amount) === 0 ? "Free" : `${amount} ${currency.toUpperCase()}`}
  </dd></div>;
}
