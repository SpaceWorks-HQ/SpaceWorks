import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { publicOrganizationKeys } from "../organizations/publicOrganizationsApi";

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type OrganizationSummary = {
  id: number;
  slug: string;
  name: string;
  governance_actions: string[];
  granted_actions: string[];
};
export type OrganizationDetail = OrganizationSummary & {
  description: string;
  website: string;
  logo_url: string | null;
  public_profile_enabled: boolean;
  is_active: boolean;
  legal_name?: string;
  registration_number?: string;
  contact_email?: string;
  billing_email?: string;
};
export type OrganizationMember = {
  id: number;
  user_id: number;
  username: string;
  display_name: string;
  email: string;
  status: "active" | "suspended";
  governance_actions: string[];
  granted_actions: string[];
  created_at: string;
  updated_at: string;
};
export type OrganizationInvitation = {
  id: number;
  organization_id: number;
  governance_actions: string[];
  granted_actions: string[];
  expires_at: string;
  redeemed_at: string | null;
  revoked_at: string | null;
  created_by_id: number | null;
  redeemed_by_id: number | null;
  created_at: string;
  state: "active" | "expired" | "revoked" | "redeemed";
};
export type CreatedInvitation = OrganizationInvitation & { token: string; redeem_path: string };

export const organizationKeys = {
  all: ["organizations"] as const,
  list: (page: number) => ["organizations", "list", page] as const,
  detail: (id: number) => ["organizations", id] as const,
  memberships: (id: number, page: number) => ["organizations", id, "memberships", page] as const,
  invitations: (id: number, page: number) => ["organizations", id, "invitations", page] as const,
};

export function useOrganizations(page = 1) {
  return useQuery({
    queryKey: organizationKeys.list(page),
    queryFn: () => staffRequest<Page<OrganizationSummary>>(`/admin/organizations/?page=${page}`),
  });
}

export function useOrganization(id: number | null) {
  return useQuery({
    queryKey: organizationKeys.detail(id ?? 0),
    queryFn: () => staffRequest<OrganizationDetail>(`/admin/organizations/${id}/`),
    enabled: id !== null,
  });
}

export function useOrganizationMemberships(id: number, page: number, enabled: boolean) {
  return useQuery({
    queryKey: organizationKeys.memberships(id, page),
    queryFn: () => staffRequest<Page<OrganizationMember>>(`/admin/organizations/${id}/memberships/?page=${page}`),
    enabled,
  });
}

export function useOrganizationInvitations(id: number, page: number, enabled: boolean) {
  return useQuery({
    queryKey: organizationKeys.invitations(id, page),
    queryFn: () => staffRequest<Page<OrganizationInvitation>>(`/admin/organizations/${id}/invitations/?page=${page}`),
    enabled,
  });
}

export function useUpdateOrganization(id: number, slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<Pick<OrganizationDetail, "name" | "slug" | "description" | "website" | "public_profile_enabled">>) =>
      staffRequest<OrganizationDetail>(`/admin/organizations/${id}/`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: async (updated) => Promise.all([
      client.invalidateQueries({ queryKey: organizationKeys.all }),
      client.invalidateQueries({ queryKey: organizationKeys.detail(id) }),
      client.invalidateQueries({ queryKey: publicOrganizationKeys.root(slug) }),
      client.invalidateQueries({ queryKey: publicOrganizationKeys.root(updated.slug) }),
    ]),
  });
}

export function useCreateOrganizationInvitation(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { governance_actions: string[]; granted_actions: string[]; expires_in_days: number }) =>
      staffRequest<CreatedInvitation>(`/admin/organizations/${id}/invitations/`, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["organizations", id, "invitations"] }),
  });
}

export function useRevokeOrganizationInvitation(organizationId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: number) => staffRequest<void>(`/admin/organization-invitations/${invitationId}/`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["organizations", organizationId, "invitations"] }),
  });
}
