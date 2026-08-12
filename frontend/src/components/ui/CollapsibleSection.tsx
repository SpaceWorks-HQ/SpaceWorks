import { useId, type ReactNode } from "react";

type CollapsibleSectionProps = {
  title: string;
  /** Shown next to the title, e.g. a machine count. */
  count?: number;
  /** Optional icon or emoji rendered before the title. */
  icon?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
};

/**
 * A titled section that expands and collapses.
 *
 * The header is a real <button> rather than a clickable div so it is reachable by
 * keyboard and announced as a control. `aria-expanded` tells assistive tech the
 * current state and `aria-controls` ties the button to the region it governs;
 * without both, a screen-reader user hears "3D Printers, button" with no
 * indication that anything opened.
 */
export function CollapsibleSection({
  title,
  count,
  icon,
  open,
  onToggle,
  children,
}: CollapsibleSectionProps) {
  const regionId = useId();
  const headingId = useId();

  return (
    <section className="overflow-hidden rounded-xl border border-line bg-panel" aria-labelledby={headingId}>
      <h3 id={headingId} className="m-0">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={regionId}
          // min-h-11 is the ~44px minimum touch target.
          className="flex min-h-11 w-full items-center gap-3 bg-surface px-3 py-2 text-left hover:bg-bg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        >
          <span
            aria-hidden="true"
            className={`text-muted transition-transform ${open ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          {icon ? <span aria-hidden="true">{icon}</span> : null}
          <span className="min-w-0 flex-1 truncate font-semibold text-ink">{title}</span>
          {count !== undefined ? (
            <span className="shrink-0 text-sm text-muted">
              <span aria-hidden="true">{count}</span>
              {/* One text node, not `{count} items`: the accessible-name algorithm
                  trims each node and joins with no separator, so a split phrase is
                  announced as "3items". The visible glyph stays the bare number and
                  is aria-hidden, so the announced name comes from this node alone --
                  which is also the only place plurals can be got right. */}
              <span className="sr-only">{`${count} ${count === 1 ? "item" : "items"}`}</span>
            </span>
          ) : null}
        </button>
      </h3>
      {/* Unmounted rather than hidden: a collapsed section's contents must not be
          reachable by Tab, and hidden-but-present rows are a classic focus trap. */}
      {/* The empty div is NOT dead weight: the toggle carries `aria-controls={regionId}`,
          and dropping the element entirely leaves that pointing at an id that does not
          exist, which is an ARIA violation. Children are still unmounted while collapsed --
          that is what keeps them off the Tab order. */}
      {open ? <div id={regionId}>{children}</div> : <div id={regionId} hidden />}
    </section>
  );
}
