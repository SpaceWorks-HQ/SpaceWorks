import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";

const iconControlClassName = "desk-button min-h-11 min-w-11 justify-center px-2";

type IconButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "aria-label" | "children" | "title" | "type"
> & {
  label: string;
  children: ReactNode;
};

type IconLinkProps = Omit<LinkProps, "aria-label" | "children" | "title"> & {
  label: string;
  children: ReactNode;
};

export function IconButton({ children, className, label, ...props }: IconButtonProps) {
  return (
    <button
      {...props}
      aria-label={label}
      className={[iconControlClassName, className].filter(Boolean).join(" ")}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

export function IconLink({ children, className, label, ...props }: IconLinkProps) {
  return (
    <Link
      {...props}
      aria-label={label}
      className={[iconControlClassName, className].filter(Boolean).join(" ")}
      title={label}
    >
      {children}
    </Link>
  );
}
