export const deviceQueryKeys = {
  root: (space: number) => ["devices", space] as const,
  list: (space: number, page: number) => ["devices", space, "list", page] as const,
  detail: (space: number, id: string) => ["devices", space, "detail", id] as const,
};
