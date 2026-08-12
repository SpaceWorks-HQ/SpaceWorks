import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addMachineOperator,
  collectionResults,
  deleteMachineOperator,
  getMachineOperators,
  getOperatorCandidates,
  machineKeys,
  type MachineAccessLevel,
} from "../../machinesApi";

export function OperatorsTab({ machineId, canDelegate }: { machineId: number; canDelegate: boolean }) {
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState("");
  const [accessLevel, setAccessLevel] = useState<MachineAccessLevel>("operate");
  const operators = useQuery({
    queryKey: machineKeys.operators(machineId),
    queryFn: () => getMachineOperators(machineId),
  });
  const candidates = useQuery({
    queryKey: machineKeys.operatorCandidates(machineId),
    queryFn: () => getOperatorCandidates(machineId),
    enabled: canDelegate,
  });
  const items = collectionResults(operators.data);
  const assignedUsers = new Set(items.map((operator) => operator.user));
  const eligibleCandidates = (candidates.data ?? []).filter((candidate) => !assignedUsers.has(candidate.user_id));
  const add = useMutation({
    mutationFn: () => addMachineOperator(machineId, {
      user_id: Number(userId),
      access_level: accessLevel,
    }),
    onSuccess: async () => {
      setUserId("");
      await queryClient.invalidateQueries({ queryKey: machineKeys.operators(machineId) });
    },
  });
  const remove = useMutation({
    mutationFn: (userPk: number) => deleteMachineOperator(machineId, userPk),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: machineKeys.operators(machineId) }),
  });

  return (
    <section>
      <h3 className="title-section mb-3">Operators</h3>
      {operators.isLoading ? <p className="text-sm text-muted">Loading operators...</p> : null}
      {operators.error instanceof Error ? <p className="text-sm text-danger">{operators.error.message}</p> : null}
      {!operators.isLoading && !operators.error && !items.length ? (
        <p className="text-sm text-muted">No operators assigned.</p>
      ) : null}
      <div className="grid gap-2">
        {items.map((operator) => (
          <div key={operator.id} className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg p-2 text-sm">
            <span className="font-medium text-ink">{operator.username}</span>
            <span className="text-muted">{operator.access_level}</span>
            {canDelegate ? (
              <button className="desk-button-danger ml-auto" type="button" disabled={remove.isPending}
                onClick={() => remove.mutate(operator.user)}>Remove</button>
            ) : null}
          </div>
        ))}
      </div>
      {canDelegate ? (
        <form className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
          <label className="eyebrow grid gap-1">Member
            <select className="desk-input" value={userId} disabled={candidates.isLoading}
              onChange={(event) => setUserId(event.target.value)} required>
              <option value="">{candidates.isLoading ? "Loading members..." : "Select a member"}</option>
              {eligibleCandidates.map((candidate) => (
                <option key={candidate.user_id} value={candidate.user_id}>
                  {candidate.display_name ? `${candidate.display_name} (${candidate.username})` : candidate.username}
                </option>
              ))}
            </select>
          </label>
          <label className="eyebrow grid gap-1">Access level
            <select className="desk-input" value={accessLevel}
              onChange={(event) => setAccessLevel(event.target.value as MachineAccessLevel)}>
              <option value="operate">Operate</option>
              <option value="manage">Manage</option>
              <option value="full">Full</option>
            </select>
          </label>
          <button className="desk-button-primary" type="submit" disabled={add.isPending || !userId}>
            {add.isPending ? "Adding..." : "Add"}
          </button>
        </form>
      ) : null}
      {candidates.error instanceof Error ? <p className="mt-2 text-sm text-danger">{candidates.error.message}</p> : null}
      {add.error instanceof Error ? <p className="mt-2 text-sm text-danger">{add.error.message}</p> : null}
      {remove.error instanceof Error ? <p className="mt-2 text-sm text-danger">{remove.error.message}</p> : null}
    </section>
  );
}
