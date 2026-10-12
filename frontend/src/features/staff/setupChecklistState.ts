export type SetupState = { profile_set: boolean; hours_set: boolean; first_item_added: boolean; staff_invited: boolean; modules_chosen: boolean };
export function setupSteps(state: SetupState, modules: readonly string[]) {
  return [
    { key: "profile_set", label: "Set the profile and location", tab: "settings" },
    { key: "hours_set", label: "Set opening hours", tab: "settings" },
    ...(modules.includes("public_inventory") ? [{ key: "first_item_added", label: "Add your first item", tab: "inventory" }] : []),
    { key: "staff_invited", label: "Invite staff", tab: "users" },
    { key: "modules_chosen", label: "Choose modules", tab: "modules" },
  ].map(step => ({ ...step, complete: state[step.key as keyof SetupState] }));
}
