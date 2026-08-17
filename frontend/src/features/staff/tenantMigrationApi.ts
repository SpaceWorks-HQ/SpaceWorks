import { staffRequest } from "../../lib/api";
import type {
  ClosureApproval,
  ClosureApprovalCreate,
  ClosureIdentity,
  CutoverOutcome,
  CutoverReceiptRequest,
  DataExportDownloadUrl,
  DeploymentIdentity,
  ImportCreate,
  ImportDecisionList,
  ImportJob,
  ImportRun,
  MigrationExportCreate,
  MigrationExportJob,
  Pairing,
  PairingCreate,
  PendingClosure,
  VerificationReport,
} from "../../generated/api";

export type {
  ClosureApproval,
  ClosureIdentity,
  CutoverOutcome,
  DeploymentIdentity,
  ImportIdentityDecision,
  ImportJob,
  MigrationExportJob,
  Pairing,
  PendingClosure,
  ReceiptEnvelope,
  VerificationReport,
} from "../../generated/api";

export const tenantMigrationKeys = {
  all: ["tenant-migration"] as const,
  deploymentIdentity: ["tenant-migration", "deployment-identity"] as const,
  pairings: ["tenant-migration", "pairings"] as const,
  imports: ["tenant-migration", "imports"] as const,
  import: (jobId: string) => ["tenant-migration", "imports", jobId] as const,
  identities: (jobId: string) => ["tenant-migration", "imports", jobId, "identities"] as const,
  verification: (jobId: string) => ["tenant-migration", "imports", jobId, "verification"] as const,
  closure: (makerspaceId: number) => ["tenant-migration", makerspaceId, "closure"] as const,
  approvals: (makerspaceId: number) => ["tenant-migration", makerspaceId, "approvals"] as const,
  exports: (makerspaceId: number) => ["tenant-migration", makerspaceId, "exports"] as const,
  export: (makerspaceId: number, jobId: string) => ["tenant-migration", makerspaceId, "exports", jobId] as const,
};

const sourceBase = (makerspaceId: number) =>
  `/admin/makerspace/${makerspaceId}/tenant-migration`;
const platformBase = "/admin/platform/tenant-migrations";

export const getDeploymentIdentity = () =>
  staffRequest<DeploymentIdentity>(`${platformBase}/deployment-identity`);
export const listPairings = () => staffRequest<Pairing[]>(`${platformBase}/pairings`);
export const createPairing = (payload: PairingCreate) =>
  staffRequest<Pairing>(`${platformBase}/pairings`, {
    method: "POST", body: JSON.stringify(payload),
  });

export const listImports = () => staffRequest<ImportJob[]>(`${platformBase}/imports`);
export function createImport(payload: Omit<ImportCreate, "archive"> & { archive: File }) {
  const body = new FormData();
  body.append("archive", payload.archive);
  body.append("source_archive_digest", payload.source_archive_digest);
  return staffRequest<ImportJob>(`${platformBase}/imports`, { method: "POST", body });
}
export const getImport = (jobId: string) =>
  staffRequest<ImportJob>(`${platformBase}/imports/${jobId}`);
export const listImportIdentities = (jobId: string) =>
  staffRequest<ClosureIdentity[]>(`${platformBase}/imports/${jobId}/identity-decisions`);
export const submitIdentityDecisions = (jobId: string, payload: ImportDecisionList) =>
  staffRequest<ImportJob>(`${platformBase}/imports/${jobId}/identity-decisions`, {
    method: "POST", body: JSON.stringify(payload),
  });
export const runImport = (jobId: string, payload: ImportRun) =>
  staffRequest<ImportJob>(`${platformBase}/imports/${jobId}/run`, {
    method: "POST", body: JSON.stringify(payload),
  });
export const getVerification = (jobId: string) =>
  staffRequest<VerificationReport>(`${platformBase}/imports/${jobId}/verification`);
export const activateTarget = (jobId: string, pairingId: string, payload: CutoverReceiptRequest) =>
  staffRequest<CutoverOutcome>(`${platformBase}/imports/${jobId}/pairings/${pairingId}/activate`, {
    method: "POST", body: JSON.stringify(payload),
  });
export const abortTarget = (jobId: string, pairingId: string) =>
  staffRequest<CutoverOutcome>(`${platformBase}/imports/${jobId}/pairings/${pairingId}/abort`, {
    method: "POST",
  });

export const getDisclosureClosure = (makerspaceId: number) =>
  staffRequest<PendingClosure>(`${sourceBase(makerspaceId)}/disclosure-closure`);
export const listDisclosureApprovals = (makerspaceId: number) =>
  staffRequest<ClosureApproval[]>(`${sourceBase(makerspaceId)}/disclosure-approvals`);
export const approveDisclosure = (makerspaceId: number, payload: ClosureApprovalCreate) =>
  staffRequest<ClosureApproval>(`${sourceBase(makerspaceId)}/disclosure-approvals`, {
    method: "POST", body: JSON.stringify(payload),
  });
export const revokeDisclosure = (makerspaceId: number, approvalId: string) =>
  staffRequest<ClosureApproval>(`${sourceBase(makerspaceId)}/disclosure-approvals/${approvalId}/revoke`, {
    method: "POST",
  });
export const listMigrationExports = (makerspaceId: number) =>
  staffRequest<MigrationExportJob[]>(`${sourceBase(makerspaceId)}/exports`);
export const createMigrationExport = (makerspaceId: number, payload: MigrationExportCreate) =>
  staffRequest<MigrationExportJob>(`${sourceBase(makerspaceId)}/exports`, {
    method: "POST", body: JSON.stringify(payload),
  });
export const getMigrationExport = (makerspaceId: number, jobId: string) =>
  staffRequest<MigrationExportJob>(`${sourceBase(makerspaceId)}/exports/${jobId}`);
export const issueMigrationDownload = (makerspaceId: number, jobId: string) =>
  staffRequest<DataExportDownloadUrl>(`${sourceBase(makerspaceId)}/exports/${jobId}/download-url`, {
    method: "POST",
  });
export const quiesceSource = (makerspaceId: number, jobId: string) =>
  staffRequest<CutoverOutcome>(`${sourceBase(makerspaceId)}/exports/${jobId}/quiesce`, { method: "POST" });
export const archiveSource = (makerspaceId: number, pairingId: string) =>
  staffRequest<CutoverOutcome>(`${sourceBase(makerspaceId)}/pairings/${pairingId}/archive-source`, { method: "POST" });
export const recoverSource = (makerspaceId: number, pairingId: string, payload: CutoverReceiptRequest) =>
  staffRequest<CutoverOutcome>(`${sourceBase(makerspaceId)}/pairings/${pairingId}/recover`, {
    method: "POST", body: JSON.stringify(payload),
  });
