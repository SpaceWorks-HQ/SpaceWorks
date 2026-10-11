export type Toast = { id: number; message: string; tone: "success" | "error" | "info"; undo?: () => Promise<unknown>; undoKey?: string; busy?: boolean };
let nextId = 0;
let session = 0;
let rows: Toast[] = [];
const listeners = new Set<() => void>();
const timers = new Map<number, ReturnType<typeof setTimeout>>();
const publish = () => listeners.forEach(listener => listener());
export const toastStore = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  snapshot: () => rows,
};

export const toastSession = () => session;
export function clearToasts() {
  session++;
  timers.forEach(clearTimeout); timers.clear();
  rows = []; publish();
}

/** A newer edit retires the older compensation for this resource. */
export function invalidateToastUndo(key: string) {
  rows = rows.map(row => row.undoKey === key ? { ...row, undo: undefined } : row);
  publish();
}

export function dismissToast(id: number) {
  if (rows.find(row => row.id === id)?.busy) return;
  clearTimeout(timers.get(id)); timers.delete(id);
  rows = rows.filter(row => row.id !== id); publish();
}

/** Undo is an awaited compensating server call, supplied only by reversible actions. */
export function toast(message: string, options: { tone?: Toast["tone"]; undo?: Toast["undo"]; undoKey?: string; duration?: number } = {}) {
  const id = ++nextId;
  rows = [...rows, { id, message, tone: options.tone ?? "success", undo: options.undo, undoKey: options.undoKey }]; publish();
  if (options.tone !== "error") timers.set(id, setTimeout(() => dismissToast(id), options.duration ?? 8000));
  return id;
}

export async function undoToast(id: number) {
  const row = rows.find(value => value.id === id);
  if (!row?.undo || row.busy) return;
  const startedIn = session;
  clearTimeout(timers.get(id)); timers.delete(id);
  rows = rows.map(value => value.id === id ? { ...value, busy: true } : value); publish();
  try {
    await row.undo();
    if (startedIn !== session) return;
    rows = rows.filter(value => value.id !== id); publish();
    toast("Action undone.");
  } catch (error) {
    if (startedIn !== session) return;
    rows = rows.map(value => value.id === id ? { id, tone: "error", message: `Could not undo: ${error instanceof Error ? error.message : "Please refresh and try again."}` } : value);
    publish();
  }
}
