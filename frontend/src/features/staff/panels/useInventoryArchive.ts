import { useMutation } from "@tanstack/react-query";
import { staffRequest } from "../../../lib/api";
import { invalidateToastUndo, toast, toastSession } from "../../../components/ui/toastStore";
import type { AdminProduct } from "./InventoryPanelShared";

const changing = new Set<number>();
const undoKey = (id: number) => `inventory-archive:${id}`;
async function change(product: AdminProduct, isArchived: boolean) {
  if (changing.has(product.id)) throw new Error("This item's archive change is still in progress.");
  changing.add(product.id);
  invalidateToastUndo(undoKey(product.id));
  const session = toastSession();
  try {
    await staffRequest(`/admin/inventory/${product.id}`, { method: "PATCH", body: JSON.stringify({ is_archived: isArchived }) });
    return session;
  } finally { changing.delete(product.id); }
}

export function useInventoryArchive(invalidate: () => void, close: () => void) {
  const archive = useMutation({
    onMutate: () => toastSession(),
    mutationFn: (product: AdminProduct) => change(product, true),
    onSuccess: (session, product) => {
      if (session !== toastSession()) return;
      close(); invalidate();
      toast(`${product.name} archived.`, { undoKey: undoKey(product.id), undo: async () => {
        await change(product, false);
        invalidate();
      } });
    },
    onError: (error, _product, session) => { if (session === toastSession()) toast(error.message, { tone: "error" }); },
  });
  const unarchive = useMutation({
    onMutate: () => toastSession(),
    mutationFn: (product: AdminProduct) => change(product, false),
    onSuccess: (session, product) => {
      if (session !== toastSession()) return;
      invalidate();
      toast(`${product.name} restored.`, { undoKey: undoKey(product.id), undo: async () => {
        await change(product, true);
        invalidate();
      } });
    },
    onError: (error, _product, session) => { if (session === toastSession()) toast(error.message, { tone: "error" }); },
  });
  return { archive, unarchive };
}
