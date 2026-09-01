import type { QueryClient } from "@tanstack/react-query";

export function invalidateInventoryViews(queryClient: QueryClient, makerspaceId: number, slug?: string) {
  queryClient.invalidateQueries({ queryKey: ["inventory", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["inventory-all", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["operations-report"] });
  queryClient.invalidateQueries({ queryKey: ["ledger", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["ledger", "all"] });
  if (slug) invalidatePublicInventory(queryClient, slug);
}

export function invalidatePublicInventory(queryClient: QueryClient, slug?: string) {
  queryClient.invalidateQueries({ queryKey: ["public-inventory"] });
  queryClient.invalidateQueries({ queryKey: ["public-inventory-detail"] });
  if (slug) {
    queryClient.invalidateQueries({ queryKey: ["public-categories", slug] });
    queryClient.invalidateQueries({ queryKey: ["tenant-bootstrap", slug] });
  }
}

export function invalidatePrintingViews(queryClient: QueryClient, makerspaceId: number | "all") {
  if (makerspaceId !== "all") {
    queryClient.invalidateQueries({ queryKey: ["print-printers", makerspaceId] });
    queryClient.invalidateQueries({ queryKey: ["print-spools", makerspaceId] });
    queryClient.invalidateQueries({ queryKey: ["print-requests", makerspaceId] });
  }
  queryClient.invalidateQueries({ queryKey: ["printer-service-report"] });
  queryClient.invalidateQueries({ queryKey: ["operations-report"] });
}

export function invalidateContainerViews(queryClient: QueryClient, makerspaceId: number, containerId?: number) {
  queryClient.invalidateQueries({ queryKey: ["containers", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["containers-all", makerspaceId] });
  if (containerId) {
    queryClient.invalidateQueries({ queryKey: ["container-contents", containerId] });
    queryClient.invalidateQueries({ queryKey: ["container-history", containerId] });
  }
}

export function invalidateQrViews(queryClient: QueryClient, makerspaceId: number, qrId?: number) {
  invalidateContainerViews(queryClient, makerspaceId);
  queryClient.invalidateQueries({ queryKey: ["qr-batches", makerspaceId] });
  if (qrId) queryClient.invalidateQueries({ queryKey: ["qr-image", qrId] });
}
