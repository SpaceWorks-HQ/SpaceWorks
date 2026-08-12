import { Link } from "react-router-dom";
import { Card } from "../../components/ui/Card";
import { StatusResult } from "./PublicPrintRequestParts";
import type { PrintStatus } from "./publicApi";

type StatusProps = { submitted: boolean; tokenStatus?: PrintStatus; tokenStatusPending: boolean; tokenStatusError: Error | null };
export function PrintStatusPanel({ submitted, tokenStatus, tokenStatusPending, tokenStatusError }: StatusProps) { return <Card className="border-secondary bg-secondary/15 text-secondary-ink"><h2 className="title-panel">Status tracker</h2>{submitted ? <p className="mt-3 text-sm">Request submitted. This browser keeps its private token; do not share the link.</p> : null}<div className="mt-4"><StatusResult error={tokenStatusError} isPending={tokenStatusPending} status={tokenStatus} /></div></Card>; }
export function PrintAccessLoadingPanel() { return <section className="mx-auto max-w-screen-sm px-5 py-6"><Card><p className="text-sm text-muted">Loading printer service...</p></Card></section>; }
export function PrintAccessErrorPanel() { return <section className="mx-auto max-w-screen-sm px-5 py-6"><Card><p className="text-sm text-danger">Could not load printer service. Try again in a moment.</p></Card></section>; }
export function PrintUnavailablePanel({ catalogPath, tokenStatus, tokenStatusPending, tokenStatusError }: { catalogPath: string; tokenStatus?: PrintStatus; tokenStatusPending: boolean; tokenStatusError: Error | null }) { return <section className="mx-auto max-w-screen-sm px-5 py-6"><Card className="border-secondary"><p className="eyebrow text-secondary-ink">3D printing</p><h2 className="title-panel mt-2">Printer service is not currently available.</h2>{tokenStatus || tokenStatusPending || tokenStatusError ? <div className="mt-4"><StatusResult error={tokenStatusError} isPending={tokenStatusPending} status={tokenStatus} /></div> : null}<Link className="desk-button mt-4" to={catalogPath}>Back to inventory</Link></Card></section>; }
