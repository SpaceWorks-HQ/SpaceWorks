export type ProcurementMachineTypeOption = { id: number; name: string };

/** The options endpoint's payload. `machine_type_required` is SERVER-derived. */
export type ProcurementMachineTypeOptions = {
  machine_type_required: boolean;
  results: ProcurementMachineTypeOption[];
};

export function procurementMachineTypeOptions(
  data: ProcurementMachineTypeOptions | undefined,
) {
  return data?.results ?? [];
}

/**
 * Whether the create form must demand a machine type.
 *
 * Read from the server, never derived from effective actions: a null-`assigned_role`
 * legacy membership is scope-exempt and cannot be expressed client-side, and holding
 * `manage_machines` is a different question from being narrowed by machine scope (a role
 * with `manage_makerspace` holds it and is exempt). Defaults to `false` while the query is
 * in flight so the form never demands a value before the options that satisfy it exist.
 */
export function procurementMachineTypeRequired(
  data: ProcurementMachineTypeOptions | undefined,
) {
  return data?.machine_type_required ?? false;
}
