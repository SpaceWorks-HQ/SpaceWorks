import { useCallback, useState } from "react";

export type ServiceActionName =
  | "accept"
  | "reject"
  | "start"
  | "complete"
  | "fail"
  | "collect"
  | "reprint";

export type ServiceDraft = {
  action: { id: number; name: ServiceActionName } | null;
  actionValues: {
    machine_id: string;
    consumable_pool_id: string;
    estimated_minutes: string;
    planned_quantity: string;
    actual_minutes: string;
    actual_quantity: string;
    percent_complete: string;
    reason: string;
  };
  manual: {
    machine_id: string;
    consumable_pool_id: string;
    duration_minutes: string;
    quantity: string;
    outcome: string;
    percent_complete: string;
    reason: string;
    note: string;
  };
};

export function blankServiceDraft(): ServiceDraft {
  return {
    action: null,
    actionValues: {
      machine_id: "",
      consumable_pool_id: "",
      estimated_minutes: "60",
      planned_quantity: "",
      actual_minutes: "0",
      actual_quantity: "",
      percent_complete: "0",
      reason: "",
    },
    manual: {
      machine_id: "",
      consumable_pool_id: "",
      duration_minutes: "",
      quantity: "",
      outcome: "success",
      percent_complete: "100",
      reason: "",
      note: "",
    },
  };
}

// Drafts persist across COLLAPSE (so an accidental toggle does not discard typing) but must
// NOT persist across JOBS. Carrying a finished job's machine, pool and grams into the next
// request's form lets an operator confirm a prefilled value and reserve or reconcile the wrong
// consumable amount -- a data-integrity bug, not a UX wrinkle. Clearing `action` alone is not
// enough, because the values live beside it.
export function clearedActionDraft(draft: ServiceDraft): ServiceDraft {
  return { ...draft, action: null, actionValues: blankServiceDraft().actionValues };
}

export function useServiceDrafts() {
  const [drafts, setDrafts] = useState<Record<number, ServiceDraft>>({});

  const draftFor = useCallback(
    (machineTypeId: number) => drafts[machineTypeId] ?? blankServiceDraft(),
    [drafts],
  );
  const setDraft = useCallback(
    (machineTypeId: number, update: (draft: ServiceDraft) => ServiceDraft) => {
      setDrafts((current) => {
        const previous = current[machineTypeId] ?? blankServiceDraft();
        return { ...current, [machineTypeId]: update(previous) };
      });
    },
    [],
  );

  return { draftFor, setDraft };
}
