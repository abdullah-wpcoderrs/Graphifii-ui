import { InputHTMLAttributes, forwardRef, useId } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  error?: string;
  hint?: string;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, hint, id, className, ...props },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;

  const classes = ["ui-input", error ? "ui-input-has-error" : null, className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="ui-input-field">
      {label && (
        <label className="ui-input-label" htmlFor={inputId}>
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        className={classes}
        aria-invalid={Boolean(error)}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        {...props}
      />
      {hint && !error && (
        <span className="ui-input-hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="ui-input-error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
});
