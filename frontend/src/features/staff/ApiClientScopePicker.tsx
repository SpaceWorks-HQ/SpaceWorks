import { useMemo } from "react";

import type { ApiClientScopeOption } from "./apiClientsApi";

export function ApiClientScopePicker({
  options,
  selected,
  onChange,
  disabled = false,
}: {
  options: ApiClientScopeOption[];
  selected: readonly string[];
  onChange: (scopes: string[]) => void;
  disabled?: boolean;
}) {
  const checked = useMemo(() => new Set(selected), [selected]);
  const grouped = useMemo(() => {
    const groups = new Map<string, ApiClientScopeOption[]>();
    options.forEach((option) => {
      groups.set(option.group, [...(groups.get(option.group) ?? []), option]);
    });
    return groups;
  }, [options]);

  const toggle = (value: string, grantable: boolean) => {
    if (disabled || !grantable) return;
    const next = new Set(checked);
    if (next.has(value)) next.delete(value); else next.add(value);
    onChange(options.filter((option) => next.has(option.value)).map((option) => option.value));
  };

  return (
    <div className="grid gap-2" aria-label="API client scopes">
      {Array.from(grouped.entries()).map(([group, groupOptions]) => (
        <section key={group} className="grid gap-2 rounded-md border border-line p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">{group}</h4>
          {groupOptions.map((option) => (
            <label key={option.value} className="flex items-start gap-3">
              <input
                className="mt-1 h-4 w-4 accent-accent"
                type="checkbox"
                checked={checked.has(option.value)}
                disabled={disabled || !option.grantable}
                onChange={() => toggle(option.value, option.grantable)}
              />
              <span className="grid gap-0.5">
                <span className="font-semibold text-ink">{option.label}</span>
                <span className="text-xs text-muted">{option.description}</span>
                {!option.grantable ? (
                  <span className="text-xs text-danger">
                    {option.lock_reason ?? "This scope cannot be granted here."}
                  </span>
                ) : null}
              </span>
            </label>
          ))}
        </section>
      ))}
    </div>
  );
}
