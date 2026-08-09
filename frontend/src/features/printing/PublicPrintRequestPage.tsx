import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { formatSlug } from "../inventory/PublicInventoryParts";
import { useTenantBootstrap } from "../inventory/usePublicInventory";
import { PrintDetailsForm, initialForm, optional, type FormState } from "./PublicPrintRequestForm";
import { fetchPrintQueues, fetchPublicConsumablePools, fetchPrintStatus, presignPrintUpload, submitPrintRequest, uploadToStorage } from "./publicApi";
import { PrintAccessErrorPanel, PrintAccessLoadingPanel, PrintStatusPanel, PrintUnavailablePanel } from "./PublicPrintRequestPanels";
import { uploadPrintFilesBounded } from "./PublicPrintUploads";
import { SkipLink } from "../../components/SkipLink";

export function PublicPrintRequestPage() {
  const queryClient = useQueryClient();
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const [form, setForm] = useState<FormState>(initialForm);
  const [modelFiles, setModelFiles] = useState<File[]>([]);
  const [screenshotFiles, setScreenshotFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [activeStatusToken, setActiveStatusToken] = useState("");
  const [website, setWebsite] = useState("");
  const statusLinkHandledRef = useRef(false);
  const bootstrapQuery = useTenantBootstrap(makerspaceSlug, tenant.mode === "central");
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const modules = useMemo(() => tenant.mode === "single" ? tenant.modules : new Set(bootstrap?.modules ?? []), [bootstrap?.modules, tenant]);
  const moduleEnabled = modules.has("machine_service");
  const queuesQuery = useQuery({ queryKey: ["public-printer-queues", makerspaceSlug], queryFn: () => fetchPrintQueues(makerspaceSlug), enabled: Boolean(makerspaceSlug) && moduleEnabled });
  const poolsQuery = useQuery({ queryKey: ["public-printer-consumable-pools", makerspaceSlug], queryFn: () => fetchPublicConsumablePools(makerspaceSlug), enabled: Boolean(makerspaceSlug) && moduleEnabled });
  const printerAvailable = Boolean(queuesQuery.data?.length);
  const enabled = moduleEnabled && printerAvailable;
  const statusQuery = useQuery({ queryKey: ["public-printer-status", activeStatusToken], queryFn: () => fetchPrintStatus(activeStatusToken), enabled: Boolean(activeStatusToken), refetchInterval: (query) => {
    const status = query.state.data?.status;
    return status === "in_progress" ? 30_000 : status === "pending" || status === "accepted" ? 90_000 : false;
  }});
  const statusStorageKey = makerspaceSlug ? `tinkerspace.printStatus.${makerspaceSlug}` : "";
  useEffect(() => { if (statusLinkHandledRef.current) return; statusLinkHandledRef.current = true; const token = new URLSearchParams(window.location.search).get("token")?.trim(); const stored = statusStorageKey ? window.localStorage.getItem(statusStorageKey)?.trim() : ""; if (token || stored) setActiveStatusToken(token || stored || ""); }, [statusStorageKey]);
  useEffect(() => { if (statusStorageKey && activeStatusToken) window.localStorage.setItem(statusStorageKey, activeStatusToken); }, [activeStatusToken, statusStorageKey]);
  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) { setForm((current) => ({ ...current, [key]: value })); }
  const submitMutation = useMutation({ mutationFn: async () => {
    const files = [...modelFiles.map((file) => ({ file, kind: "stl" as const })), ...screenshotFiles.map((file) => ({ file, kind: "screenshot" as const }))];
    const fileIds = await uploadPrintFilesBounded(files, async (item) => { const presigned = await presignPrintUpload(makerspaceSlug, { kind: item.kind, filename: item.file.name, content_type: item.kind === "stl" ? item.file.type || "application/octet-stream" : item.file.type }); await uploadToStorage(presigned.upload, item.file); return presigned.file_id; }, setUploadProgress);
    const chosenPool = poolsQuery.data?.find((pool) => String(pool.id) === form.consumablePoolId);
    return submitPrintRequest(makerspaceSlug, { website, queue_id: queuesQuery.data?.[0]?.id ?? null, title: form.title.trim(), project_brief: optional(form.projectBrief), preferred_settings: optional(form.preferredSettings), material: chosenPool?.material, color: chosenPool?.color, consumable_pool_id: form.consumablePoolId ? Number(form.consumablePoolId) : null, estimated_filament_grams: form.estimatedFilamentGrams.trim() || null, quantity: form.quantity, source_link: optional(form.sourceLink), file_ids: fileIds });
  }, onSuccess: (response) => { queryClient.invalidateQueries({ queryKey: ["public-printer-consumable-pools", makerspaceSlug] }); setUploadProgress(""); setSubmitted(true); setActiveStatusToken(response.public_token); }, onError: () => setUploadProgress("") });
  const displayName = bootstrap?.branding.display_name || bootstrap?.makerspace.name || formatSlug(makerspaceSlug) || "Makerspace";
  return <main className="desk-shell">
    <SkipLink /><header className="border-b border-line bg-panel"><div className="mx-auto flex max-w-screen-xl flex-col gap-4 px-5 py-6 sm:px-8"><p className="text-sm font-semibold tracking-wide text-accent-ink">Public 3D Print Request</p><div className="flex flex-wrap items-end justify-between gap-3"><div><MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace.logo_url} size="lg" /><p className="mt-2 text-sm text-muted">Submit print files and keep your private token link to check progress.</p></div><div className="flex gap-2"><SpaceWorksBadge /><Link className="desk-button" to={tenantPath()}>Back to inventory</Link></div></div></div></header><div id="main-content" tabIndex={-1}>{bootstrapQuery.isLoading || (moduleEnabled && queuesQuery.isLoading) ? <PrintAccessLoadingPanel /> : null}{bootstrapQuery.isError || queuesQuery.isError ? <PrintAccessErrorPanel /> : null}{!bootstrapQuery.isLoading && !queuesQuery.isLoading && !bootstrapQuery.isError && !queuesQuery.isError && !enabled ? <PrintUnavailablePanel catalogPath={tenantPath()} tokenStatus={statusQuery.data} tokenStatusPending={Boolean(activeStatusToken) && statusQuery.isPending} tokenStatusError={statusQuery.error} /> : null}{enabled ? <section className="mx-auto grid max-w-screen-xl grid-cols-1 gap-5 px-5 py-6 sm:px-8 lg:grid-cols-[minmax(0,1fr)_360px]"><PrintDetailsForm form={form} updateField={updateField} poolsQuery={poolsQuery} modelFiles={modelFiles} setModelFiles={setModelFiles} screenshotFiles={screenshotFiles} setScreenshotFiles={setScreenshotFiles} submitPending={submitMutation.isPending} submitError={submitMutation.error} uploadProgress={uploadProgress} website={website} onWebsiteChange={setWebsite} onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (form.title.trim()) submitMutation.mutate(); }} /><aside><PrintStatusPanel submitted={submitted} tokenStatus={statusQuery.data} tokenStatusPending={Boolean(activeStatusToken) && statusQuery.isPending} tokenStatusError={statusQuery.error} /></aside></section> : null}</div></main>;
}
