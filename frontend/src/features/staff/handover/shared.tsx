import type { Dispatch, FormEvent, SetStateAction } from "react";

import type { HandoverRequest, HandoverRequestItem, ReturnField, ReturnValues } from "./types";

export function submit(event: FormEvent<HTMLFormElement>, action: () => void) {
  event.preventDefault();
  action();
}

export function DialogError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Request failed";
  return <p className="text-sm text-danger">{message}</p>;
}

export function QuantityInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1">
      <span className="text-xs font-medium text-muted">{label}</span>
      <input
        className="desk-input"
        type="number"
        min="0"
        step="1"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function defaultReturnValues(row: HandoverRequest) {
  return Object.fromEntries(
    row.items.map((item) => [
      item.id,
      {
        returned: String(remainingQuantity(item)),
        damaged: "0",
        missing: "0",
      },
    ]),
  ) as Record<number, ReturnValues>;
}

export function remainingQuantity(item: HandoverRequestItem) {
  return item.issued_quantity - item.returned_quantity - item.damaged_quantity - item.missing_quantity;
}

export function parseReturnValues(value: ReturnValues) {
  return {
    returned: parseQuantity(value.returned),
    damaged: parseQuantity(value.damaged),
    missing: parseQuantity(value.missing),
  };
}

function parseQuantity(value: string) {
  if (value.trim() === "") return 0;
  return Number(value);
}

export function valuesAreValid(value: { returned: number; damaged: number; missing: number }) {
  return Object.values(value).every((quantity) => Number.isInteger(quantity) && quantity >= 0);
}

export function updateReturnValue(
  setValues: Dispatch<SetStateAction<Record<number, ReturnValues>>>,
  itemId: number,
  field: ReturnField,
  value: string,
) {
  setValues((current) => ({
    ...current,
    [itemId]: {
      ...(current[itemId] ?? { returned: "0", damaged: "0", missing: "0" }),
      [field]: value,
    },
  }));
}
