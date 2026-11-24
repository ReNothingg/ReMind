import { useEffect, useState } from 'react';
import { fetchApi, writeApiJson as writeProject } from '../../services/api/transport';

export type Project = { id: string; name: string };

export function useProjects(owner: number | undefined) {
  const [state, setState] = useState<{ owner: number | undefined; entries: Project[] }>({ owner: undefined, entries: [] });
  const [failedOwner, setFailedOwner] = useState<number>();
  useEffect(() => {
    if (!owner) return;
    const controller = new AbortController();
    fetchApi<{ workspaces: Project[] }>('/api/workspaces', { signal: controller.signal })
      .then(({ workspaces }) => {
        if (!controller.signal.aborted) {
          setState({ owner, entries: workspaces });
          setFailedOwner(undefined);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailedOwner(owner);
      });
    return () => controller.abort();
  }, [owner]);

  const update = (change: (current: Project[]) => Project[]) =>
    setState((state) => ({ owner, entries: change(state.owner === owner ? state.entries : []) }));

  async function save(name: string, id?: string) {
    const result = await writeProject<Project>(
      id ? '/api/workspaces/' + encodeURIComponent(id) : '/api/workspaces',
      id ? 'PATCH' : 'POST',
      { name }
    );
    update((rows) => (id ? rows.map((row) => (row.id === id ? result : row)) : [...rows, result]));
    return result;
  }

  async function remove(id: string) {
    await writeProject('/api/workspaces/' + encodeURIComponent(id), 'DELETE');
    update((rows) => rows.filter((row) => row.id !== id));
  }

  async function moveChat(id: string, project: string | null) {
    await writeProject('/api/workspaces/chats/' + encodeURIComponent(id), 'PUT', {
      workspace_id: project,
    });
  }

  return {
    projects: state.owner === owner ? state.entries : [],
    loaded: state.owner === owner,
    loadError: failedOwner !== undefined && failedOwner === owner,
    save,
    remove,
    moveChat,
  };
}
