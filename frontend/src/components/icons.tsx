type IconProps = {
  className?: string;
};

export function ChartIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      focusable="false"
      height="20"
      viewBox="0 0 20 20"
      width="20"
    >
      <path
        d="M3 17h14M5 14V9h3v5m1 0V4h3v10m1 0V7h3v7"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.75"
      />
    </svg>
  );
}

export function MoonIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      focusable="false"
      height="20"
      viewBox="0 0 20 20"
      width="20"
    >
      <path
        d="M16.5 12.25A7 7 0 0 1 7.75 3.5a7 7 0 1 0 8.75 8.75Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.75"
      />
    </svg>
  );
}

export function SunIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      focusable="false"
      height="20"
      viewBox="0 0 20 20"
      width="20"
    >
      <circle cx="10" cy="10" r="3.25" stroke="currentColor" strokeWidth="1.75" />
      <path
        d="M10 2v1.5M10 16.5V18M2 10h1.5M16.5 10H18M4.34 4.34 5.4 5.4m9.2 9.2 1.06 1.06m0-11.32L14.6 5.4m-9.2 9.2-1.06 1.06"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.75"
      />
    </svg>
  );
}

export function UserIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      focusable="false"
      height="20"
      viewBox="0 0 20 20"
      width="20"
    >
      <circle cx="10" cy="6.5" r="3" stroke="currentColor" strokeWidth="1.75" />
      <path
        d="M4 17c.55-3 2.7-4.75 6-4.75S15.45 14 16 17"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.75"
      />
    </svg>
  );
}
