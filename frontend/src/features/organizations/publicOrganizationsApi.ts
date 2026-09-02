import { useQuery } from "@tanstack/react-query";

import { publicV1Request } from "../../lib/api";

export type PublicOrganization = {
  slug: string;
  name: string;
  description: string;
  website: string;
  logo_url: string | null;
  catalogue_links: { events: string };
};

export type OrganizationPublicEvent = {
  public_token: string;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  location: string;
  capacity: number;
  availability: "Available" | "Limited" | "Full";
  image_url: string | null;
  status: "published";
  host: { slug: string; name: string; logo_url: string | null };
};

export type Page<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export const publicOrganizationKeys = {
  root: (slug: string) => ["public-organization", slug] as const,
  events: (slug: string, page: number) =>
    ["public-organization", slug, "events", page] as const,
};

export function usePublicOrganization(slug: string) {
  return useQuery({
    queryKey: publicOrganizationKeys.root(slug),
    queryFn: () => publicV1Request<PublicOrganization>(
      `/public/organizations/${encodeURIComponent(slug)}/`,
    ),
    enabled: Boolean(slug),
  });
}

export function usePublicOrganizationEvents(slug: string, page: number) {
  return useQuery({
    queryKey: publicOrganizationKeys.events(slug, page),
    queryFn: () => publicV1Request<Page<OrganizationPublicEvent>>(
      `/public/organizations/${encodeURIComponent(slug)}/events/?page=${page}`,
    ),
    enabled: Boolean(slug),
  });
}
