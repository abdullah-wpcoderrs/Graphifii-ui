type SpinnerProps = {
  size?: "sm" | "md" | "lg";
  className?: string;
  label?: string;
};

export function Spinner({ size = "md", className, label = "Loading" }: SpinnerProps) {
  const classes = ["ui-spinner", `ui-spinner-${size}`, className]
    .filter(Boolean)
    .join(" ");

  return <span className={classes} role="status" aria-label={label} />;
}
