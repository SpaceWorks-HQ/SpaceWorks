import type React from "react";
import { useEffect, useId, useRef, useSyncExternalStore } from "react";
import {
  consumePendingRestore,
  focusFirstDialogElement,
  getSnapshot,
  popDialog,
  pushDialog,
  subscribe,
  trapDialogFocus,
} from "./dialogFocus";

type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: "md" | "xl";
  backdrop?: "plain" | "blur";
};

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
  backdrop = "plain",
}: ModalProps) {
  const titleId = useId();
  const layerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const tokenRef = useRef<symbol | null>(null);
  const top = useSyncExternalStore(subscribe, getSnapshot);
  const amTop = top === tokenRef.current;
  const amTopRef = useRef(amTop);
  amTopRef.current = amTop;
  const maxWidthClass = size === "xl" ? "max-w-4xl" : "max-w-lg";
  const backdropClass =
    backdrop === "blur" ? "bg-ink/35 backdrop-blur-sm" : "bg-ink/40";
  // Keep onClose in a ref so the focus effect depends only on `open`. Callers pass a
  // fresh inline onClose every render; if it were in the dep array, every keystroke
  // (which re-renders the parent) would re-run this effect and steal focus back to the
  // first field. The ref lets Escape always call the latest onClose without that churn.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const token = pushDialog({
      previousFocus,
      getPanel: () => panelRef.current,
      getLayer: () => layerRef.current,
    });
    tokenRef.current = token;
    const panel = panelRef.current;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!amTopRef.current) return;
      if (event.key === "Escape") onCloseRef.current();
      if (panel) trapDialogFocus(event, panel);
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      popDialog(token);
      if (tokenRef.current === token) tokenRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    if (!amTop) return;
    consumePendingRestore(panelRef.current);
    // Initial focus lives HERE, not in the push effect. A dialog that opens while another sits
    // above it renders with `inert` on its layer, and `inert` is only cleared by the re-render
    // that follows becoming topmost -- so focusing from the push effect silently fails, and
    // consumePendingRestore no-ops because nothing was popped. This effect runs post-commit,
    // once `inert` is gone. jsdom implements no `inert` at all, so no unit test can catch this.
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) focusFirstDialogElement(panel);
  }, [amTop]);

  if (!open) return null;

  return (
    <div
      ref={layerRef}
      inert={!amTop}
      className={`fixed inset-0 z-50 grid place-items-center ${backdropClass} p-3 sm:p-4`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal={amTop ? "true" : undefined}
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`desk-panel flex max-h-[calc(100dvh-1.5rem)] w-full ${maxWidthClass} flex-col overflow-hidden focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus sm:max-h-[calc(100dvh-2rem)]`}
      >
        <div className="shrink-0 border-b border-line px-4 py-3">
          <h2 id={titleId} className="title-section">
            {title}
          </h2>
        </div>
        <div className="desk-panel-body overflow-y-auto overflow-x-hidden min-w-0 p-4">{children}</div>
        {footer ? <div className="shrink-0 border-t border-line px-4 py-3">{footer}</div> : null}
      </div>
    </div>
  );
}
