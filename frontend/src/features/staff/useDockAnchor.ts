import { useLayoutEffect, useState, type CSSProperties } from "react";

const POPOVER_WIDTH = 256;
const VIEWPORT_GUTTER = 16;
const ANCHOR_GAP = 8;

export type DockPopoverPosition = Pick<CSSProperties, "bottom" | "left">;

export function useDockAnchor(anchor: HTMLButtonElement | null, open: boolean): DockPopoverPosition {
  const [position, setPosition] = useState<DockPopoverPosition>({
    bottom: 0,
    left: VIEWPORT_GUTTER,
  });

  useLayoutEffect(() => {
    if (!open || !anchor) return undefined;

    const updatePosition = () => {
      const bounds = anchor.getBoundingClientRect();
      const dockBounds = anchor.closest<HTMLElement>("[data-staff-dock-root]")?.getBoundingClientRect();
      const availableWidth = Math.max(0, window.innerWidth - (VIEWPORT_GUTTER * 2));
      const popoverWidth = Math.min(POPOVER_WIDTH, availableWidth);
      const idealLeft = bounds.left + (bounds.width / 2) - (popoverWidth / 2);
      const maximumLeft = Math.max(VIEWPORT_GUTTER, window.innerWidth - popoverWidth - VIEWPORT_GUTTER);
      const viewportLeft = Math.min(Math.max(VIEWPORT_GUTTER, idealLeft), maximumLeft);

      setPosition({
        bottom: (dockBounds?.bottom ?? window.innerHeight) - bounds.top + ANCHOR_GAP,
        left: viewportLeft - (dockBounds?.left ?? 0),
      });
    };

    const scroller = anchor.closest<HTMLElement>("[data-staff-dock-scroller]");
    updatePosition();
    scroller?.addEventListener("scroll", updatePosition, { passive: true });
    window.addEventListener("resize", updatePosition);

    return () => {
      scroller?.removeEventListener("scroll", updatePosition);
      window.removeEventListener("resize", updatePosition);
    };
  }, [anchor, open]);

  return position;
}
