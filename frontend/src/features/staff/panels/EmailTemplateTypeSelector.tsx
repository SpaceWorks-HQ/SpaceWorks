import { Badge } from "../../../components/ui";

export type MachineTypeOption = {
  id: number;
  name: string;
  is_active: boolean;
  is_overridden: boolean;
};

export function EmailTemplateTypeSelector({
  canEditSpaceDefault,
  types,
  selectedTypeId,
  onSelect,
}: {
  canEditSpaceDefault: boolean;
  types: MachineTypeOption[];
  selectedTypeId: number | null;
  onSelect: (machineType: MachineTypeOption | null) => void;
}) {
  return (
    <div className="grid gap-2 rounded-md border border-line bg-bg p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">Machine type</p>
      <div className="flex flex-wrap gap-2">
        {canEditSpaceDefault ? (
          <AxisButton selected={selectedTypeId === null} label="Space default" onClick={() => onSelect(null)} />
        ) : null}
        {types.map((machineType) => (
          <AxisButton
            key={machineType.id}
            selected={selectedTypeId === machineType.id}
            label={machineType.name}
            edited={machineType.is_overridden}
            onClick={() => onSelect(machineType)}
          />
        ))}
      </div>
    </div>
  );
}

function AxisButton({
  selected,
  label,
  edited = false,
  onClick,
}: {
  selected: boolean;
  label: string;
  edited?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${
        selected ? "border-accent bg-surface text-accent-ink" : "border-line bg-bg text-ink hover:border-accent"
      }`}
      type="button"
      onClick={onClick}
    >
      {label}
      {edited ? <Badge tone="warn">Edited</Badge> : null}
    </button>
  );
}
