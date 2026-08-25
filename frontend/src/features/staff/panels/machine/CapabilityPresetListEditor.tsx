import { useId, useState } from "react";

type Props = {
  label: string;
  singularLabel: string;
  values: string[];
  disabled?: boolean;
  onChange: (values: string[]) => void;
};

export function CapabilityPresetListEditor({ label, singularLabel, values, disabled = false, onChange }: Props) {
  const inputId = useId();
  const errorId = useId();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  const addValue = () => {
    const value = draft.trim();
    if (!value) {
      setError(`${singularLabel} cannot be blank.`);
      return;
    }
    if (values.some((existing) => existing.toLocaleLowerCase() === value.toLocaleLowerCase())) {
      setError(`${singularLabel} already exists.`);
      return;
    }
    onChange([...values, value]);
    setDraft("");
    setError("");
  };

  return (
    <fieldset className="grid gap-2 rounded-lg border border-line p-3" disabled={disabled}>
      <legend className="eyebrow px-1">{label}</legend>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <label className="eyebrow grid gap-1" htmlFor={inputId}>
          New {singularLabel.toLocaleLowerCase()}
          <input
            id={inputId}
            className="desk-input min-h-11 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            value={draft}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => { setDraft(event.target.value); setError(""); }}
          />
        </label>
        <button className="desk-button-secondary min-h-11 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" type="button" onClick={addValue}>
          Add {singularLabel.toLocaleLowerCase()}
        </button>
      </div>
      {error ? <p id={errorId} className="text-sm text-danger" role="alert">{error}</p> : null}
      {values.length ? (
        <ul className="flex flex-wrap gap-2">
          {values.map((value) => (
            <li key={value} className="flex items-center gap-1 rounded-lg bg-surface p-1 pl-3 text-sm text-ink">
              <span>{value}</span>
              <button
                aria-label={`Remove ${singularLabel.toLocaleLowerCase()} ${value}`}
                className="desk-button-ghost min-h-11 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                type="button"
                onClick={() => onChange(values.filter((existing) => existing !== value))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">No presets. The consumable form will use free text.</p>}
    </fieldset>
  );
}
