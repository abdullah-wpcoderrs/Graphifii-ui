import Link from "next/link";
import { ReactNode } from "react";

type EmptyStateAction = {
  label: string;
  href: string;
};

type EmptyStateProps = {
  title: string;
  description?: string;
  action?: EmptyStateAction;
  icon?: ReactNode;
};

export function EmptyState({ title, description, action, icon }: EmptyStateProps) {
  return (
    <div className="ui-empty-state">
      {icon && <div className="ui-empty-state-icon">{icon}</div>}
      <strong className="ui-empty-state-title">{title}</strong>
      {description && <p className="ui-empty-state-description">{description}</p>}
      {action && (
        <Link className="ui-button ui-button-secondary ui-button-md" href={action.href}>
          <span className="ui-button-label">{action.label}</span>
        </Link>
      )}
    </div>
  );
}
