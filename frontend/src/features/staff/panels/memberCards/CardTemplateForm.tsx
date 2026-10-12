import { useEffect, useState } from "react";

import { CollapsibleSection, Field } from "../../../../components/ui";
import { useCardTemplate, useSaveCardTemplate } from "./api";
import { CARD_FRONT_FIELDS, type CardTemplate } from "./types";

const PAGES: CardTemplate["page"][] = ["a4", "letter", "cr80"];
const ORIENTATIONS: CardTemplate["orientation"][] = ["portrait", "landscape"];
const MM_FIELDS = [
  ["card_width_mm", "Card width (mm)"],
  ["card_height_mm", "Card height (mm)"],
  ["margin_mm", "Page margin (mm)"],
  ["gap_mm", "Gap between cards (mm)"],
  ["name_font_size_pt", "Name font size (pt)"],
  ["font_size_pt", "Other text size (pt)"],
] as const;

const TOGGLES = [
  ["include_photo", "Print the member photo"],
  ["include_qr", "Print the card QR code"],
  ["crop_marks", "Print crop marks"],
] as const;

/** The print template. Collapsed by default: it is set once per makerspace and then left
 *  alone, so it must not push the card list and the scan box below the fold. */
export function CardTemplateForm({ makerspaceId }: { makerspaceId: number }) {
  const [open, setOpen] = useState(false);
  const template = useCardTemplate(makerspaceId);
  const save = useSaveCardTemplate(makerspaceId);
  const [draft, setDraft] = useState<CardTemplate | null>(null);
  const [dirty, setDirty] = useState(false);

  // Seed once, and re-seed only while the form has no unsaved edits — otherwise a
  // background refetch would silently discard what the operator just typed.
  useEffect(() => {
    if (!template.data || dirty) return;
    setDraft(template.data);
  }, [template.data, dirty]);

  const patch = (changes: Partial<CardTemplate>) => {
    if (!draft) return;
    setDirty(true);
    setDraft({ ...draft, ...changes });
  };
  const toggleField = (field: string, checked: boolean) => {
    if (!draft) return;
    const next = checked
      ? [...draft.front_fields, field]
      : draft.front_fields.filter((value) => value !== field);
    patch({ front_fields: next });
  };

  return (
    <CollapsibleSection title="Card layout" open={open} onToggle={() => setOpen(!open)}>
      <div className="p-4">
        {template.isLoading ? <p className="text-sm text-muted">Loading the template…</p> : null}
        {template.error ? (
          <p className="text-sm text-danger" role="alert">
            {template.error instanceof Error ? template.error.message : "Could not load the template."}
          </p>
        ) : null}
        {draft ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Page">
                <select
                  className="desk-input"
                  value={draft.page}
                  onChange={(event) => patch({ page: event.target.value as CardTemplate["page"] })}
                >
                  {PAGES.map((value) => (
                    <option key={value} value={value}>
                      {value.toUpperCase()}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Orientation">
                <select
                  className="desk-input"
                  value={draft.orientation}
                  onChange={(event) =>
                    patch({ orientation: event.target.value as CardTemplate["orientation"] })
                  }
                >
                  {ORIENTATIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>
              {MM_FIELDS.map(([key, label]) => (
                <Field key={key} label={label}>
                  <input
                    className="desk-input"
                    type="number"
                    min={0}
                    step="0.5"
                    value={draft[key]}
                    onChange={(event) => patch({ [key]: Number(event.target.value) } as Partial<CardTemplate>)}
                  />
                </Field>
              ))}
            </div>

            <fieldset className="mt-4 border-0 p-0">
              <legend className="eyebrow">Fields printed on the front</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {CARD_FRONT_FIELDS.map((field) => (
                  <label key={field} className="flex items-center gap-2 text-sm text-ink">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={draft.front_fields.includes(field)}
                      onChange={(event) => toggleField(field, event.target.checked)}
                    />
                    {field.replace(/_/g, " ")}
                  </label>
                ))}
              </div>
            </fieldset>

            <Field label="Back-of-card text" className="mt-4">
              <textarea
                className="desk-input"
                rows={3}
                value={draft.back_text}
                onChange={(event) => patch({ back_text: event.target.value })}
              />
            </Field>

            <div className="mt-4 grid gap-2">
              {TOGGLES.map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={draft[key]}
                    onChange={(event) => patch({ [key]: event.target.checked } as Partial<CardTemplate>)}
                  />
                  {label}
                </label>
              ))}
            </div>

            {save.error ? (
              <p className="mt-3 text-sm text-danger" role="alert">
                {save.error instanceof Error ? save.error.message : "Could not save the layout."}
              </p>
            ) : null}
            <button
              className="desk-button-secondary mt-4"
              type="button"
              disabled={save.isPending}
              onClick={() => save.mutate(draft, { onSuccess: () => setDirty(false) })}
            >
              {save.isPending ? "Saving…" : "Save layout"}
            </button>
          </>
        ) : null}
      </div>
    </CollapsibleSection>
  );
}
