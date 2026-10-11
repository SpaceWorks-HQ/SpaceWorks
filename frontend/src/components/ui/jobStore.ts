export type TrayJob = { key: string; label: string; makerspaceId: number; endpoint: string; status: string; collectionId?: string; session?: number };
let rows: TrayJob[] = [];
let session = 0;
export const getJobSession = () => session;
const listeners = new Set<() => void>();
const publish = () => listeners.forEach(listener => listener());
export const jobStore = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  snapshot: () => rows,
};
export const jobRunning = (status: string) => ["pending", "queued", "running", "building", "promoting"].includes(status);
export function trackJob(job: TrayJob, startedSession = session) {
  if (startedSession !== session) return;
  rows = [...rows.filter(row => row.key !== job.key), { ...job, session }].slice(-30); publish();
}
export function updateJob(key: string, status: string, startedSession = session) {
  if (startedSession !== session) return;
  if (rows.find(row => row.key === key)?.status === status) return;
  rows = rows.map(row => row.key === key ? { ...row, status } : row); publish();
}
export function dismissJob(key: string) { rows = rows.filter(row => row.key !== key); publish(); }
export function clearJobs() { session += 1; rows = []; publish(); }
