import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Panel, useStaffGet, type Makerspace } from "./shared";
import { staffRequest } from "../../../lib/api";

type NotificationLevel = "info" | "warning" | "critical";

type NotificationEntry = {
  id: number;
  level: NotificationLevel;
  event: string;
  title: string;
  body: string;
  url_path: string;
  read_at: string | null;
  created_at: string;
};

type NotificationResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: NotificationEntry[];
};

export function NotificationInbox({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const params = new URLSearchParams();
  if (unreadOnly) params.set("unread", "true");
  params.set("page", String(page));
  const query = params.toString();
  const notifications = useStaffGet<NotificationResponse>(
    ["notifications", makerspace.id, query],
    `/notifications/makerspace/${makerspace.id}?${query}`,
  );
  const invalidateNotifications = () => {
    queryClient.invalidateQueries({ queryKey: ["notifications", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["notifications-unread-count", makerspace.id] });
  };
  const markRead = useMutation({
    mutationFn: (id: number) =>
      staffRequest<NotificationEntry>(`/notifications/makerspace/${makerspace.id}/${id}/read`, {
        method: "POST",
      }),
    onSuccess: invalidateNotifications,
  });
  const markAllRead = useMutation({
    mutationFn: () =>
      staffRequest<{ updated: number }>(`/notifications/makerspace/${makerspace.id}/read-all`, {
        method: "POST",
      }),
    onSuccess: invalidateNotifications,
  });

  const updateUnreadOnly = (checked: boolean) => {
    setUnreadOnly(checked);
    setPage(1);
  };

  return (
    <Panel title="Notifications">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <label className="eyebrow inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(event) => updateUnreadOnly(event.target.checked)}
          />
          Unread only
        </label>
        <button
          className="desk-button-success"
          disabled={markAllRead.isPending || notifications.data?.count === 0}
          onClick={() => markAllRead.mutate()}
        >
          Mark all read
        </button>
      </div>
      {notifications.isLoading ? <p className="mb-3 text-sm text-muted">Loading notifications...</p> : null}
      {notifications.error ? <p className="mb-3 text-sm text-danger">{notifications.error.message}</p> : null}
      {markRead.error ? <p className="mb-3 text-sm text-danger">{markRead.error.message}</p> : null}
      {markAllRead.error ? <p className="mb-3 text-sm text-danger">{markAllRead.error.message}</p> : null}
      <div className="grid gap-3">
        {notifications.data?.results.map((notification) => {
          const unread = notification.read_at === null;
          return (
            <article
              key={notification.id}
              className={`rounded-lg border border-line bg-bg p-3 ${unread ? "shadow-soft" : "opacity-80"}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className={`status-box ${levelClassName(notification.level)}`}>
                      {notification.level}
                    </span>
                    {notification.event ? <span className="text-xs text-muted">{notification.event}</span> : null}
                    <span className="font-mono text-xs text-muted">{formatRelativeTime(notification.created_at)}</span>
                  </div>
                  <h3 className="title-section break-words">{notification.title}</h3>
                  {notification.body ? (
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-muted">
                      {notification.body}
                    </p>
                  ) : null}
                  {notification.url_path ? (
                    <a className="mt-2 inline-block text-sm font-medium text-accent-ink" href={notification.url_path}>
                      Open
                    </a>
                  ) : null}
                </div>
                {unread ? (
                  <button
                    className="desk-button-success shrink-0"
                    disabled={markRead.isPending}
                    onClick={() => markRead.mutate(notification.id)}
                  >
                    Mark read
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
        {notifications.data && notifications.data.results.length === 0 ? (
          <p className="py-4 text-sm text-muted">No notifications.</p>
        ) : null}
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 text-sm">
        <button
          className="desk-button-ghost"
          disabled={!notifications.data?.previous}
          onClick={() => setPage((current) => Math.max(1, current - 1))}
        >
          Previous
        </button>
        <span className="text-muted">
          Page {page}{" - "}{notifications.data?.count ?? 0} total
        </span>
        <button
          className="desk-button-ghost"
          disabled={!notifications.data?.next}
          onClick={() => setPage((current) => current + 1)}
        >
          Next
        </button>
      </div>
    </Panel>
  );
}

function levelClassName(level: NotificationLevel) {
  if (level === "critical") return "status-box-danger";
  if (level === "warning") return "status-box-pending";
  return "status-box-active";
}

function formatRelativeTime(value: string) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const diffSeconds = Math.round((timestamp - Date.now()) / 1000);
  const absSeconds = Math.abs(diffSeconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absSeconds < 60) return formatter.format(diffSeconds, "second");
  const diffMinutes = Math.round(diffSeconds / 60);
  if (Math.abs(diffMinutes) < 60) return formatter.format(diffMinutes, "minute");
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) return formatter.format(diffHours, "hour");
  const diffDays = Math.round(diffHours / 24);
  if (Math.abs(diffDays) < 30) return formatter.format(diffDays, "day");
  const diffMonths = Math.round(diffDays / 30);
  if (Math.abs(diffMonths) < 12) return formatter.format(diffMonths, "month");
  return formatter.format(Math.round(diffMonths / 12), "year");
}
