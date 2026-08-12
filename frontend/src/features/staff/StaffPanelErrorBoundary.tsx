import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  resetKey: string;
};

type State = {
  error: Error | null;
};

export class StaffPanelErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Staff panel render failed", error, info);
  }

  componentDidUpdate(previous: Props) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <section className="desk-panel p-6" role="alert">
        <h2 className="title-panel">This page could not be displayed</h2>
        <p className="mt-2 text-sm text-muted">
          The rest of Space Works is still available. Reload this page to try again.
        </p>
        <button className="desk-button-primary mt-4" type="button" onClick={() => window.location.reload()}>
          Reload page
        </button>
      </section>
    );
  }
}
