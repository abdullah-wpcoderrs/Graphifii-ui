import { ReactNode } from "react";
import { Button } from "./button";

type ErrorStateProps = {
  title: string;
  description?: string;
  onRetry?: () => void;
  retryLabel?: string;
  icon?: ReactNode;
};

export function ErrorState({
  title,
  description,
  onRetry,
  retryLabel = "Try again",
  icon,
}: ErrorStateProps) {
  return (
    <div className="ui-error-state" role="alert">
      {icon && <div className="ui-error-state-icon">{icon}</div>}
      <strong className="ui-error-state-title">{title}</strong>
      {description && <p className="ui-error-state-description">{description}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}
