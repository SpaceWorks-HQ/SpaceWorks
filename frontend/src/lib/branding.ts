import type { TenantBootstrap } from "./api";

// Public/member colour overrides are page-scoped; keep the branding import surface stable.
export { readBrandTokens, tenantColourStyle } from "./brandColours";

const DEFAULT_FAVICON =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Ctext x='50%25' y='50%25' dominant-baseline='central' text-anchor='middle' font-size='48'%3E%F0%9F%93%A6%3C/text%3E%3C/svg%3E";

function setFavicon(url: string) {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.href = url;
}

export function applyTenantBranding(bootstrap: TenantBootstrap) {
  const name =
    bootstrap.branding.display_name ||
    bootstrap.makerspace.name ||
    "Space Works";
  document.title = name;
  if (typeof bootstrap.theme.logo_url === "string" && bootstrap.theme.logo_url) {
    setFavicon(bootstrap.theme.logo_url);
  } else {
    setFavicon(DEFAULT_FAVICON);
  }
}
