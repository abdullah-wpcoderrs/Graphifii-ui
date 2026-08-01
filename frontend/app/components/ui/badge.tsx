import { ReactNode } from "react";

type BadgeTone = "neutral" | "success" | "info" | "danger" | "warning";

type BadgeProps = {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
  pulse?: boolean;
};

export function Badge({ tone = "neutral", children, className, pulse = false }: BadgeProps) {
  const classes = ["ui-badge", `ui-badge-${tone}`, className]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes}>
      <i className={pulse ? "is-pulsing" : undefined} aria-hidden="true" />
      {children}
    </span>
  );
}
