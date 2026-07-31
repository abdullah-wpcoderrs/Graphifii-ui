import Link from "next/link";
import { BrandLockup } from "./brand-lockup";

type RecoveryScreenProps = {
  code: string;
  eyebrow: string;
  title: string;
  description: string;
  guidance: string;
  reference?: string | null;
  primaryLabel: string;
  primaryHref: string;
  secondaryLabel: string;
  secondaryHref: string;
};

export function RecoveryScreen({
  code,
  eyebrow,
  title,
  description,
  guidance,
  reference,
  primaryLabel,
  primaryHref,
  secondaryLabel,
  secondaryHref,
}: RecoveryScreenProps) {
  return (
    <main className="system-page">
      <section className="system-shell" aria-labelledby="system-title">
        <BrandLockup priority />

        <div className="system-content">
          <p className="system-code" aria-hidden="true">
            {code}
          </p>
          <p className="system-eyebrow">{eyebrow}</p>
          <h1 id="system-title">{title}</h1>
          <p className="system-description">{description}</p>

          <div className="system-guidance">
            <span className="security-indicator" aria-hidden="true" />
            <p>{guidance}</p>
          </div>

          {reference && (
            <dl className="system-reference">
              <dt>Safe reference</dt>
              <dd>{reference}</dd>
            </dl>
          )}

          <div className="system-actions">
            <Link className="action-primary" href={primaryHref}>
              {primaryLabel}
            </Link>
            <Link className="action-secondary" href={secondaryHref}>
              {secondaryLabel}
            </Link>
          </div>
        </div>

        <p className="system-footer">
          Sensitive error details are kept out of the browser.
        </p>
      </section>
    </main>
  );
}
