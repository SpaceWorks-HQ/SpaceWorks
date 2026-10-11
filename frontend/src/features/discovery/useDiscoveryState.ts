import { useSearchParams } from "react-router-dom";
import { currentMonth } from "./calendarDates";
export { currentMonth, monthWindow } from "./calendarDates";

export function validMonth(value: string) {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value) && Number(value.slice(0, 4)) >= 1900 && Number(value.slice(0, 4)) <= 9998;
}

export function useDiscoveryState(timeZone = "UTC") {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "calendar" ? "calendar" : "agenda";
  const rawMonth = params.get("month") ?? "";
  const month = validMonth(rawMonth) ? rawMonth : view === "calendar" ? currentMonth(timeZone) : "";
  function update(values: Record<string, string>) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
      return next;
    });
  }
  return { query: params.get("q") ?? "", view, month, facet: params.get("filter") ?? "", timeZone, update };
}
