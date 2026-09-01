/**
 * "Skip to main content" — the first thing in the tab order on every page.
 *
 * Visually hidden until it receives keyboard focus (see `.skip-link` in
 * index.css), so it costs sighted mouse users nothing while sparing keyboard and
 * screen-reader users from tabbing through the whole sidebar on every navigation.
 *
 * The target element must carry `id="main-content"` AND `tabIndex={-1}`: without
 * the tabindex, browsers move the *scroll* position but leave focus behind, so the
 * next Tab returns to the top of the nav and the link does nothing useful.
 */
export function SkipLink() {
  return (
    <a className="skip-link" href="#main-content">
      Skip to main content
    </a>
  );
}
