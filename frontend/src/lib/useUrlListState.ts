import { useSearchParams } from "react-router-dom";
import type { SetStateAction } from "react";

export type ListState = Record<string, string>;
const isPage = (key: string) => key === "page" || key.endsWith("Page");

export function readListState<T extends ListState>(params: URLSearchParams, defaults: T): T {
  return Object.fromEntries(Object.entries(defaults).map(([key, fallback]) => {
    const raw = params.get(key) ?? fallback;
    const value = isPage(key) ? (/^[1-9]\d{0,5}$/.test(raw) ? raw : fallback) : raw;
    return [key, value];
  })) as T;
}

/** URL is the source of truth. Router navigation restores state on Back/Forward. */
export function useUrlListState<T extends ListState>(defaults: T, prefix = "") {
  const [params, setParams] = useSearchParams();
  const localParams = (source: URLSearchParams) => new URLSearchParams(Object.keys(defaults).flatMap((key) => source.has(prefix + key) ? [[key, source.get(prefix + key)!]] : []));
  const values = readListState(localParams(params), defaults);
  const update = (patch: Partial<T>, resetPages = true) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      const state: ListState = { ...readListState(localParams(current), defaults), ...patch };
      if (resetPages) Object.keys(defaults).filter(isPage).forEach((key) => { state[key] = defaults[key]; });
      Object.keys(defaults).forEach((key) => {
        if (state[key] === defaults[key] || !state[key]) next.delete(prefix + key);
        else next.set(prefix + key, state[key]);
      });
      return next;
    });
  };
  const setFilter = (key: string, value: string) => update({ [key]: value } as Partial<T>);
  const setPage = (page: SetStateAction<number>, key: string = "page") => {
    const current = Number(values[key] ?? 1);
    const next = typeof page === "function" ? page(current) : page;
    update({ [key]: String(Math.max(1, next)) } as Partial<T>, false);
  };
  const restore = (state: ListState) => update({ ...defaults, ...Object.fromEntries(Object.entries(state).filter(([key]) => key in defaults)) } as T, false);
  const query = new URLSearchParams(values).toString();
  return { values, page: Number(values.page ?? 1), setPage, setFilter, update, restore, query };
}

export type UrlListState = { values: ListState; setFilter: (key: string, value: string) => void; restore: (state: ListState) => void };
