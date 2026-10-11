export function memberScope(path: string) {
  const match = /^(\/member|\/m\/[^/]+\/member)\/?$/.exec(path);
  return match?.[1] ?? null;
}

export function kioskScope(path: string) {
  const match = /^(\/kiosk\/|\/m\/[^/]+\/kiosk\/)[^/]+\/?$/.exec(path);
  return match?.[1] ?? null;
}
