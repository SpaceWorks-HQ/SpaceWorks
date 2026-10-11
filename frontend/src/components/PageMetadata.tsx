import { useEffect } from "react";

type Props = { title: string; description: string; path: string; image?: string | null; siteName?: string };

function absoluteUrl(value: string) {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

/** Own just these head tags while mounted; restore the previous page on cleanup.
 * Reusing existing nodes avoids duplicate metadata from the static SPA shell.
 */
export function PageMetadata({ title, description, path, image, siteName }: Props) {
  useEffect(() => {
    const previousTitle = document.title;
    const marker = document.createElement("meta");
    marker.dataset.spaceworksPageMetadata = "true";
    document.head.appendChild(marker);
    document.title = title;
    const cleanups: (() => void)[] = [];
    function tag(selector: string, name: string, attributes: Record<string, string>, value: string) {
      const existing = [...document.head.querySelectorAll<HTMLElement>(selector)];
      const node = existing[0] ?? document.createElement(name);
      const previous = node.getAttribute(name === "link" ? "href" : "content");
      const duplicates = existing.slice(1).map((element) => ({ element, next: element.nextSibling }));
      duplicates.forEach(({ element }) => element.remove());
      Object.entries(attributes).forEach(([key, content]) => node.setAttribute(key, content));
      node.setAttribute(name === "link" ? "href" : "content", value);
      if (!existing.length) document.head.appendChild(node);
      cleanups.push(() => {
        if (!existing.length) node.remove();
        else if (previous === null) node.removeAttribute(name === "link" ? "href" : "content");
        else node.setAttribute(name === "link" ? "href" : "content", previous);
        duplicates.forEach(({ element, next }) => document.head.insertBefore(element, next?.parentNode === document.head ? next : null));
      });
    }
    const canonical = absoluteUrl(path);
    tag('meta[name="description"]', "meta", { name: "description" }, description);
    tag('link[rel="canonical"]', "link", { rel: "canonical" }, canonical);
    const values = { title, description, url: canonical, type: "website", site_name: siteName ?? title, image: image ? absoluteUrl(image) : "" };
    Object.entries(values).forEach(([key, value]) => tag(`meta[property="og:${key}"]`, "meta", { property: `og:${key}` }, value));
    return () => { cleanups.reverse().forEach((cleanup) => cleanup()); marker.remove(); document.title = previousTitle; };
  }, [title, description, path, image, siteName]);
  return null;
}
