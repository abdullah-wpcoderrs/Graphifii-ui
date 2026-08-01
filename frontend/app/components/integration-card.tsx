import type { Integration } from "../lib/api";
import { Badge, Button } from "./ui";

type IntegrationCardProps = {
  integration: Integration;
  onConnect: () => void;
  onDisconnect: () => void;
  disconnecting: boolean;
};

const STATUS_TONE: Record<Integration["status"], "success" | "neutral" | "warning"> = {
  connected: "success",
  not_connected: "neutral",
  not_configured: "warning",
};

const STATUS_LABEL: Record<Integration["status"], string> = {
  connected: "Connected",
  not_connected: "Not connected",
  not_configured: "Not configured",
};

export function IntegrationCard({
  integration,
  onConnect,
  onDisconnect,
  disconnecting,
}: IntegrationCardProps) {
  const isNotConfigured = integration.status === "not_configured";

  return (
    <article className={`integration-card ${isNotConfigured ? "is-not-configured" : ""}`}>
      <div className="integration-card-header">
        <span className={`integration-card-icon is-${integration.icon}`} aria-hidden="true" />
        <div>
          <strong>{integration.name}</strong>
          {integration.login && <span className="integration-card-login">{integration.login}</span>}
        </div>
        <Badge tone={STATUS_TONE[integration.status]}>{STATUS_LABEL[integration.status]}</Badge>
      </div>

      {integration.message && <p className="integration-card-message">{integration.message}</p>}

      <div className="integration-card-actions">
        {integration.status === "connected" && integration.id !== "github" && (
          <Button variant="secondary" size="sm" onClick={onDisconnect} loading={disconnecting}>
            Disconnect
          </Button>
        )}
        {integration.status === "not_connected" && (
          <Button variant="primary" size="sm" onClick={onConnect}>
            Connect with {integration.name}
          </Button>
        )}
        {integration.status === "connected" && integration.id === "github" && (
          <span className="integration-card-note">Connected during sign-in</span>
        )}
      </div>
    </article>
  );
}
