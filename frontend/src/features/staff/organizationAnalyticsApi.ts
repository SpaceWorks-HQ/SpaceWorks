import { useQuery } from "@tanstack/react-query";

import type { ApiPath, OrganizationReportResponse } from "../../generated/api";
import { staffRequest } from "../../lib/api";
import type { ReportKey } from "./panels/operationsReportsConfig";

const ORGANIZATION_ANALYTICS_PATH: ApiPath =
  "/api/v1/admin/organizations/{organization_id}/analytics/{report_key}";

function organizationAnalyticsPath(organizationId: number, reportKey: ReportKey) {
  return ORGANIZATION_ANALYTICS_PATH
    .replace("/api/v1", "")
    .replace("{organization_id}", String(organizationId))
    .replace("{report_key}", reportKey);
}

export type {
  OrganizationReportBreakdown,
  OrganizationReportResponse,
  OrganizationReportRows,
} from "../../generated/api";

export const organizationAnalyticsKeys = {
  all: ["organization-analytics"] as const,
  report: (organizationId: number | null, reportKey: ReportKey) =>
    [...organizationAnalyticsKeys.all, organizationId, reportKey] as const,
};

export function useOrganizationAnalytics(
  organizationId: number | null,
  reportKey: ReportKey,
) {
  return useQuery({
    queryKey: organizationAnalyticsKeys.report(organizationId, reportKey),
    queryFn: () => {
      if (organizationId === null) throw new Error("Select an organization first.");
      return staffRequest<OrganizationReportResponse>(
        organizationAnalyticsPath(organizationId, reportKey),
      );
    },
    enabled: organizationId !== null,
  });
}
