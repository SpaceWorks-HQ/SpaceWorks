import { useEffect, useRef, useState, type RefObject } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { EmailTemplateTypeSelector, type MachineTypeOption } from "./EmailTemplateTypeSelector";

export type TemplateSummary = {
  stream: string;
  audience: string;
  key: string;
  label: string;
  is_active: boolean;
  is_overridden: boolean;
  can_edit_space_default: boolean;
  overridable_types: MachineTypeOption[];
};

export type SelectedTemplate = Pick<TemplateSummary, "stream" | "audience" | "key"> & {
  machineType: MachineTypeOption | null;
  canEditSpaceDefault: boolean;
  overridableTypes: MachineTypeOption[];
};

type TemplateDetail = TemplateSummary & {
  description: string;
  fields: { name: string; description: string }[];
  subject: string;
  text_body: string;
  html_body: string;
  default_subject: string;
  default_text: string;
  default_html: string;
};

type Draft = { subject: string; text_body: string; html_body: string; is_active: boolean };

type FocusedField = "subject" | "text_body" | "html_body";
type Preview = Pick<Draft, "subject" | "text_body" | "html_body">;

const emptyDraft: Draft = { subject: "", text_body: "", html_body: "", is_active: true };

export function EmailTemplateEditor({
  makerspaceId,
  selected,
  onSelectMachineType,
}: {
  makerspaceId: number;
  selected: SelectedTemplate;
  onSelectMachineType: (machineType: MachineTypeOption | null) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [debouncedDraft, setDebouncedDraft] = useState<Draft>(emptyDraft);
  const [showDefaults, setShowDefaults] = useState(false);
  const [lastFocused, setLastFocused] = useState<FocusedField>("text_body");
  const subjectRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const htmlRef = useRef<HTMLTextAreaElement>(null);
  const detailKey = [
    "email-template",
    makerspaceId,
    selected.stream,
    selected.audience,
    selected.key,
    selected.machineType?.id ?? "space",
  ];
  const path = templatePath(makerspaceId, selected);

  const detail = useQuery({
    queryKey: detailKey,
    queryFn: () => staffRequest<TemplateDetail>(path),
  });

  useEffect(() => {
    if (detail.data) {
      const next = detailToDraft(detail.data);
      setDraft(next);
      setDebouncedDraft(next);
      setShowDefaults(false);
    }
  }, [detail.data]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedDraft(draft), 400);
    return () => window.clearTimeout(timer);
  }, [draft]);

  const preview = useQuery({
    queryKey: [
      "email-template-preview",
      makerspaceId,
      selected.stream,
      selected.audience,
      selected.key,
      selected.machineType?.id ?? "space",
      debouncedDraft,
    ],
    queryFn: () =>
      staffRequest<Preview>(`/admin/makerspace/${makerspaceId}/email-templates/preview`, {
        method: "POST",
        body: JSON.stringify({
          stream: selected.stream,
          audience: selected.audience,
          key: selected.key,
          ...(selected.machineType ? { machine_type_id: selected.machineType.id } : {}),
          subject: debouncedDraft.subject,
          text_body: debouncedDraft.text_body,
          html_body: debouncedDraft.html_body,
        }),
      }),
    enabled: Boolean(detail.data),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["email-templates", makerspaceId] });
    queryClient.invalidateQueries({ queryKey: detailKey });
  };
  const save = useMutation({
    mutationFn: () =>
      staffRequest<TemplateDetail>(path, { method: "PATCH", body: JSON.stringify(draft) }),
    onSuccess: (updated) => {
      const next = detailToDraft(updated);
      setDraft(next);
      setDebouncedDraft(next);
      invalidate();
    },
  });
  const reset = useMutation({
    mutationFn: () => staffRequest<TemplateDetail>(`${path}/reset`, { method: "POST" }),
    onSuccess: (updated) => {
      const next = detailToDraft(updated);
      setDraft(next);
      setDebouncedDraft(next);
      invalidate();
    },
  });

  const insertField = (name: string) => {
    const token = `{{ ${name} }}`;
    const target = editorRef(lastFocused, subjectRef, textRef, htmlRef).current;
    const start = target?.selectionStart ?? draft[lastFocused].length;
    const end = target?.selectionEnd ?? start;
    setDraft((current) => ({
      ...current,
      [lastFocused]: `${current[lastFocused].slice(0, start)}${token}${current[lastFocused].slice(end)}`,
    }));
    window.requestAnimationFrame(() => {
      target?.focus();
      target?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  if (detail.isLoading) return <p className="text-sm text-muted">Loading template...</p>;
  if (detail.error) return <p className="text-sm text-danger">{detail.error.message}</p>;
  if (!detail.data) return <p className="text-sm text-muted">Select a template to edit.</p>;

  return (
    <div className="grid gap-4">
      <EmailTemplateTypeSelector
        canEditSpaceDefault={selected.canEditSpaceDefault}
        types={selected.overridableTypes}
        selectedTypeId={selected.machineType?.id ?? null}
        onSelect={onSelectMachineType}
      />
      <form className="grid gap-4 rounded-md border border-line bg-bg p-4" onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}>
        <TemplateHeader detail={detail.data} active={draft.is_active} typeOverride={Boolean(selected.machineType)} onActive={(is_active) => setDraft({ ...draft, is_active })} />
        <label className="eyebrow grid gap-2">
          <span>Subject</span>
          <input ref={subjectRef} className="desk-input" value={draft.subject} onFocus={() => setLastFocused("subject")} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} />
        </label>
        <MergeFields detail={detail.data} onInsert={insertField} />
        <label className="eyebrow grid gap-2">
          <span>Plain text body</span>
          <textarea ref={textRef} className="desk-input min-h-48 font-mono text-xs" value={draft.text_body} onFocus={() => setLastFocused("text_body")} onChange={(event) => setDraft({ ...draft, text_body: event.target.value })} />
        </label>
        <label className="eyebrow grid gap-2">
          <span>HTML body</span>
          <textarea ref={htmlRef} className="desk-input min-h-56 font-mono text-xs" value={draft.html_body} onFocus={() => setLastFocused("html_body")} onChange={(event) => setDraft({ ...draft, html_body: event.target.value })} />
        </label>
        <div className="desk-actions flex flex-wrap items-center gap-2">
          <button className="desk-button-primary" type="submit" disabled={save.isPending}>{save.isPending ? "Saving..." : "Save"}</button>
          <button className="desk-button-danger" type="button" disabled={reset.isPending} onClick={() => window.confirm(selected.machineType ? "Reset this override to the space default?" : "Reset this email template to the built-in default?") && reset.mutate()}>
            {reset.isPending ? "Resetting..." : selected.machineType ? "Fall back to space default" : "Reset to built-in default"}
          </button>
          <button className="desk-button-ghost" type="button" onClick={() => setShowDefaults((open) => !open)}>{showDefaults ? "Hide default" : "View default"}</button>
        </div>
        {save.error ? <p className="text-sm text-danger">{save.error.message}</p> : null}
        {reset.error ? <p className="text-sm text-danger">{reset.error.message}</p> : null}
      </form>
      {showDefaults ? <DefaultReference detail={detail.data} typeOverride={Boolean(selected.machineType)} /> : null}
      <PreviewPane preview={preview.data} loading={preview.isFetching} error={preview.error} />
    </div>
  );
}

function TemplateHeader({ detail, active, typeOverride, onActive }: { detail: TemplateDetail; active: boolean; typeOverride: boolean; onActive: (active: boolean) => void }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="title-section">{detail.label}</h3>
          <Badge tone={active ? "success" : "neutral"}>{active ? "Custom" : "Default"}</Badge>
          {detail.is_overridden ? <Badge tone="warn">Edited</Badge> : null}
        </div>
        {detail.description ? <p className="max-w-3xl text-sm text-muted">{detail.description}</p> : null}
      </div>
      <label className="flex max-w-xs items-start gap-3 text-sm text-ink">
        <input className="mt-1 h-4 w-4" type="checkbox" checked={active} onChange={(event) => onActive(event.target.checked)} />
        <span>
          <span className="font-semibold">Use custom template</span>
          <span className="block text-xs text-muted">When off, the {typeOverride ? "space" : "built-in"} default is sent (your text is kept). The email always sends.</span>
        </span>
      </label>
    </div>
  );
}

function MergeFields({ detail, onInsert }: { detail: TemplateDetail; onInsert: (name: string) => void }) {
  return (
    <div className="grid gap-2">
      <h3 className="title-section">Merge fields</h3>
      <div className="flex flex-wrap gap-2">
        {detail.fields.map((field) => (
          <button key={field.name} className="desk-button-ghost font-mono text-xs" title={field.description} type="button" onClick={() => onInsert(field.name)}>
            {field.name}
          </button>
        ))}
      </div>
    </div>
  );
}

function DefaultReference({ detail, typeOverride }: { detail: TemplateDetail; typeOverride: boolean }) {
  return (
    <div className="grid gap-3 rounded-md border border-line bg-bg p-4">
      <h3 className="title-section">{typeOverride ? "Space default reference" : "Built-in default reference"}</h3>
      <ReferenceBlock title="Subject" value={detail.default_subject} />
      <ReferenceBlock title="Plain text" value={detail.default_text} tall />
    </div>
  );
}

function ReferenceBlock({ title, value, tall = false }: { title: string; value: string; tall?: boolean }) {
  return (
    <div className="grid gap-2">
      <h4 className="title-section">{title}</h4>
      <pre className={`${tall ? "max-h-64 whitespace-pre-wrap" : ""} overflow-auto rounded-md border border-line bg-surface p-3 text-xs text-muted`}>{value || "-"}</pre>
    </div>
  );
}

function PreviewPane({ preview, loading, error }: { preview?: Preview; loading: boolean; error: Error | null }) {
  return (
    <div className="grid gap-3 rounded-md border border-line bg-bg p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="title-section">Preview</h3>
        {loading ? <span className="text-xs text-muted">Rendering...</span> : null}
      </div>
      {error ? <p className="text-sm text-danger">{error.message}</p> : null}
      <ReferenceBlock title="Subject" value={preview?.subject ?? ""} />
      <ReferenceBlock title="Plain text" value={preview?.text_body ?? ""} tall />
      {preview?.html_body ? (
        <div className="grid gap-2">
          <h4 className="title-section">HTML</h4>
          <iframe className="h-96 w-full rounded-md border border-line bg-white" sandbox="" srcDoc={preview.html_body} title="Rendered email HTML preview" />
        </div>
      ) : null}
    </div>
  );
}

function templatePath(makerspaceId: number, selected: SelectedTemplate) {
  const base = `/admin/makerspace/${makerspaceId}/email-templates/${[selected.stream, selected.audience, selected.key].map(encodeURIComponent).join("/")}`;
  return selected.machineType ? `${base}/types/${selected.machineType.id}` : base;
}

function detailToDraft(detail: TemplateDetail): Draft {
  return {
    subject: detail.subject,
    text_body: detail.text_body,
    html_body: detail.html_body,
    is_active: detail.is_active,
  };
}

function editorRef(
  focused: FocusedField,
  subjectRef: RefObject<HTMLInputElement | null>,
  textRef: RefObject<HTMLTextAreaElement | null>,
  htmlRef: RefObject<HTMLTextAreaElement | null>,
) {
  if (focused === "subject") return subjectRef;
  if (focused === "html_body") return htmlRef;
  return textRef;
}
