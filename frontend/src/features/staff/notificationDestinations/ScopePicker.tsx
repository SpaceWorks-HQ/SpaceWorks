import { type DestinationScope } from "../notificationDestinationTypes";
import { type ScopeOptions } from "./scopeOptions";

export function ScopePicker({
  onChange,
  options,
  scopeRequired = false,
  scope,
}: {
  onChange: (scope: DestinationScope) => void;
  options: ScopeOptions;
  scopeRequired?: boolean;
  scope: DestinationScope;
}) {
  const groups = [
    { key: "machine_type_ids" as const, label: "Machine types", items: options.machineTypes },
    { key: "machine_ids" as const, label: "Machines", items: options.machines },
    { key: "category_ids" as const, label: "Categories", items: options.categories },
  ].filter((group) => group.items.length > 0);

  if (groups.length === 0) return null;

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm text-muted">
        {scopeRequired
          ? "Required: choose at least one machine or machine type"
          : "Limit to (leave everything unticked to receive all alerts)"}
      </legend>
      <div className="grid gap-3 sm:grid-cols-3">
        {groups.map((group) => (
          <div key={group.key}>
            <p className="eyebrow">{group.label}</p>
            <div className="mt-1 grid max-h-40 gap-1 overflow-y-auto">
              {group.items.map((item) => (
                <label className="flex items-center gap-2 text-sm" key={item.id}>
                  <input
                    checked={scope[group.key].includes(item.id)}
                    onChange={(event) =>
                      onChange({
                        ...scope,
                        [group.key]: event.target.checked
                          ? [...scope[group.key], item.id]
                          : scope[group.key].filter((id) => id !== item.id),
                      })
                    }
                    type="checkbox"
                  />
                  <span>{item.name}</span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </fieldset>
  );
}
