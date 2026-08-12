import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getMachinePublicPreview,
  machineKeys,
  machinePublicPreviewKey,
  setMachinePublicity,
  type Machine,
  type MachinePublicPreview,
} from '../machinesApi';

function PreviewValue({ value }: { value: unknown }) {
  if (value === null) return <span className={'text-muted'}>Not set</span>;
  if (typeof value !== 'object') return <span>{String(value)}</span>;
  return (
    <dl className={'grid gap-2 border-l border-line pl-3'}>
      {Object.entries(value).map(([key, child]) => (
        <div key={key} className={'grid gap-1 sm:grid-cols-[9rem_minmax(0,1fr)]'}>
          <dt className={'text-xs font-semibold text-muted'}>
            {key.replace(/_/g, ' ')}
          </dt>
          <dd className={'min-w-0 break-words text-sm text-ink'}>
            <PreviewValue value={child} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function MachinePublicSettings({ machine, makerspaceId }: {
  machine: Machine;
  makerspaceId: number;
}) {
  const queryClient = useQueryClient();
  const preview = useQuery({
    queryKey: machinePublicPreviewKey(machine.id),
    queryFn: () => getMachinePublicPreview(machine.id),
  });
  const publicity = useMutation({
    mutationFn: (isPublic: boolean) => setMachinePublicity(machine.id, isPublic),
    onSuccess: async (serverPreview, isPublic) => {
      queryClient.setQueryData<MachinePublicPreview>(
        machinePublicPreviewKey(machine.id),
        serverPreview,
      );
      queryClient.setQueryData<Machine>(machineKeys.detail(machine.id), (current) =>
        current ? { ...current, is_public: isPublic } : current,
      );
      await queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) });
    },
  });

  return (
    <section className={'border-t border-line pt-4'}>
      <h3 className="title-section">Public listing</h3>
      <label className={'mt-3 flex items-start gap-3 rounded-xl border border-line bg-bg p-3'}>
        <input
          type={'checkbox'}
          checked={machine.is_public}
          disabled={publicity.isPending}
          onChange={(event) => publicity.mutate(event.target.checked)}
        />
        <span>
          <span className={'block text-sm font-semibold text-ink'}>Show publicly</span>
          <span className={'block text-xs text-muted'}>
            Retired machines remain hidden even when this setting is on.
          </span>
        </span>
      </label>
      {publicity.error instanceof Error ? (
        <p className={'mt-2 text-sm text-danger'}>{publicity.error.message}</p>
      ) : null}
      <div className={'mt-4 rounded-xl border border-line bg-surface p-3'}>
        <h4 className="title-section mb-3">What&apos;s shown publicly</h4>
        {preview.isLoading ? <p className={'text-sm text-muted'}>Loading preview...</p> : null}
        {preview.error instanceof Error ? (
          <p className={'text-sm text-danger'}>{preview.error.message}</p>
        ) : null}
        {preview.data ? <PreviewValue value={preview.data} /> : null}
      </div>
    </section>
  );
}
