import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { EmailTemplateEditor, type SelectedTemplate, type TemplateSummary } from "./EmailTemplateEditor";
import { Panel, type Makerspace } from "./shared";

type GroupedTemplates = {
  stream: string;
  audiences: { audience: string; templates: TemplateSummary[] }[];
}[];

export function EmailTemplatesPanel({ makerspace }: { makerspace: Makerspace }) {
  const [selected, setSelected] = useState<SelectedTemplate | null>(null);
  const list = useQuery({
    queryKey: ["email-templates", makerspace.id],
    queryFn: () =>
      staffRequest<TemplateSummary[]>(`/admin/makerspace/${makerspace.id}/email-templates`),
  });
  const rows = useMemo(() => list.data ?? [], [list.data]);

  useEffect(() => {
    if (!rows.length) {
      setSelected(null);
      return;
    }
    const current = selected
      ? rows.find(
          (row) =>
            row.stream === selected.stream &&
            row.audience === selected.audience &&
            row.key === selected.key,
        )
      : undefined;
    if (!current || !selected || !selectedAxisIsVisible(current, selected)) {
      const first = rows[0];
      setSelected(selectTemplate(first));
      return;
    }
    const currentType = selected.machineType
      ? current.overridable_types.find((item) => item.id === selected.machineType?.id) ?? null
      : null;
    if (
      selected.canEditSpaceDefault !== current.can_edit_space_default ||
      selected.overridableTypes !== current.overridable_types ||
      selected.machineType !== currentType
    ) {
      setSelected({
        ...selected,
        machineType: currentType,
        canEditSpaceDefault: current.can_edit_space_default,
        overridableTypes: current.overridable_types,
      });
    }
  }, [rows, selected]);

  const grouped = useMemo(() => groupTemplates(rows), [rows]);

  return (
    <Panel title="Email templates">
      {list.isLoading ? (
        <p className="text-sm text-muted">Loading email templates...</p>
      ) : list.error ? (
        <p className="text-sm text-danger">{list.error.message}</p>
      ) : !rows.length ? (
        <p className="text-sm text-muted">No editable email templates are available.</p>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[18rem_minmax(0,1fr)]">
          <div className="rounded-md border border-line bg-bg p-3">
            <TemplateList groups={grouped} selected={selected} onSelect={setSelected} />
          </div>
          {selected ? (
            <EmailTemplateEditor
              makerspaceId={makerspace.id}
              selected={selected}
              onSelectMachineType={(machineType) => setSelected({ ...selected, machineType })}
            />
          ) : null}
        </div>
      )}
    </Panel>
  );
}

function TemplateList({
  groups,
  selected,
  onSelect,
}: {
  groups: GroupedTemplates;
  selected: SelectedTemplate | null;
  onSelect: (template: SelectedTemplate) => void;
}) {
  return (
    <div className="grid gap-4">
      {groups.map((stream) => (
        <div key={stream.stream} className="grid gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            {formatLabel(stream.stream)}
          </h3>
          {stream.audiences.map((audience) => (
            <div key={audience.audience} className="grid gap-1">
              <p className="font-mono text-xs uppercase text-muted">
                {formatLabel(audience.audience)}
              </p>
              {audience.templates.map((template) => (
                <TemplateButton
                  key={`${template.stream}:${template.audience}:${template.key}`}
                  selected={isSelected(selected, template)}
                  template={template}
                  onSelect={onSelect}
                />
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function TemplateButton({
  selected,
  template,
  onSelect,
}: {
  selected: boolean;
  template: TemplateSummary;
  onSelect: (template: SelectedTemplate) => void;
}) {
  return (
    <button
      className={`flex min-w-0 items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm ${
        selected ? "border-accent bg-surface text-accent-ink" : "border-line bg-bg text-ink hover:border-accent"
      }`}
      type="button"
      onClick={() =>
        onSelect(selectTemplate(template))
      }
    >
      <span className="min-w-0 truncate font-semibold">{template.label}</span>
      {template.is_overridden || template.overridable_types.some((item) => item.is_overridden) ? <Badge tone="warn">Edited</Badge> : null}
    </button>
  );
}

function groupTemplates(rows: TemplateSummary[]): GroupedTemplates {
  const streams = new Map<string, Map<string, TemplateSummary[]>>();
  rows.forEach((row) => {
    if (!streams.has(row.stream)) streams.set(row.stream, new Map());
    const audiences = streams.get(row.stream)!;
    if (!audiences.has(row.audience)) audiences.set(row.audience, []);
    audiences.get(row.audience)!.push(row);
  });
  return Array.from(streams, ([stream, audiences]) => ({
    stream,
    audiences: Array.from(audiences, ([audience, templates]) => ({ audience, templates })),
  }));
}

function isSelected(selected: SelectedTemplate | null, template: TemplateSummary) {
  return (
    selected?.stream === template.stream &&
    selected.audience === template.audience &&
    selected.key === template.key
  );
}

function selectTemplate(template: TemplateSummary): SelectedTemplate {
  return {
    stream: template.stream,
    audience: template.audience,
    key: template.key,
    machineType: template.can_edit_space_default ? null : template.overridable_types[0] ?? null,
    canEditSpaceDefault: template.can_edit_space_default,
    overridableTypes: template.overridable_types,
  };
}

function selectedAxisIsVisible(template: TemplateSummary, selected: SelectedTemplate) {
  if (selected.machineType === null) return template.can_edit_space_default;
  return template.overridable_types.some((item) => item.id === selected.machineType?.id);
}

function formatLabel(value: string) {
  return value.replace(/_/g, " ");
}
