import type { ComponentType } from "react";

type StaffNavIconProps = { className?: string };

export function StaffNavFallbackIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <circle cx="4" cy="10" r="1" />
      <circle cx="10" cy="10" r="1" />
      <circle cx="16" cy="10" r="1" />
    </svg>
  );
}

function OperateIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d="M3 4.5h14M5.5 4.5v11M14.5 4.5v11M5.5 8h9M5.5 12h9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function InventoryIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d="m3 6 7-3 7 3-7 3-7-3Zm0 0v8l7 3 7-3V6M10 9v8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MachinesIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d="M7.5 3h5l.6 2.1 2 .8 1.9-1 2.5 4.2-1.6 1.5.3 2.2 1.3 1.7-3.5 3.3-1.8-1.2-2.2.4-.9 2H7.1l-.8-2-2.2-.4-1.8 1.2-2.1-4.1 1.5-1.5-.2-2.2L0 9l2.5-4.1 2 1 2-.8L7.5 3Z" strokeLinecap="round" strokeLinejoin="round" transform="scale(.8) translate(2.5 1)" />
      <circle cx="10" cy="10" r="2.5" />
    </svg>
  );
}

function EventsIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <rect x="3" y="4.5" width="14" height="12.5" rx="2" />
      <path d="M6.5 3v3M13.5 3v3M3 8h14m-9.5 3h1m3 0h1m-5 3h1m3 0h1" strokeLinecap="round" />
    </svg>
  );
}

function BookingsIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <circle cx="10" cy="10" r="7" />
      <path d="M10 6v4l2.5 1.5M7 2.5V4m6-1.5V4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MembersIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <circle cx="7" cy="7" r="3" />
      <circle cx="14.5" cy="8" r="2" />
      <path d="M2.5 17c.4-3.2 2-5 4.5-5s4.1 1.8 4.5 5m.4-4.2c2.8-.8 4.8.6 5.3 3.2" strokeLinecap="round" />
    </svg>
  );
}

function InsightsIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d="M3 17V9h3v8H3Zm5.5 0V3h3v14h-3Zm5.5 0v-5h3v5h-3Z" strokeLinejoin="round" />
    </svg>
  );
}

function AdminIcon({ className }: StaffNavIconProps) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d="M3 5h6m4 0h4M3 10h2m4 0h8M3 15h8m4 0h2" strokeLinecap="round" />
      <circle cx="11" cy="5" r="2" />
      <circle cx="7" cy="10" r="2" />
      <circle cx="13" cy="15" r="2" />
    </svg>
  );
}

export const STAFF_NAV_ICONS: Record<string, ComponentType<StaffNavIconProps>> = {
  Operate: OperateIcon,
  Inventory: InventoryIcon,
  Machines: MachinesIcon,
  Events: EventsIcon,
  Bookings: BookingsIcon,
  Members: MembersIcon,
  Insights: InsightsIcon,
  Admin: AdminIcon,
};
