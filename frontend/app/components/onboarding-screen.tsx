import Image from "next/image";
import Link from "next/link";
import type { OnboardingContent } from "../lib/onboarding";
import { BrandLockup } from "./brand-lockup";

type OnboardingScreenProps = {
  content: OnboardingContent;
};

const SETUP_STEPS = [
  {
    label: "GitHub identity",
    description: "Signed in as maya-chen",
  },
  {
    label: "GitHub App installation",
    description: "Organization or personal installation",
  },
  {
    label: "Repository access",
    description: "Only repositories selected in GitHub",
  },
];

export function OnboardingScreen({ content }: OnboardingScreenProps) {
  return (
    <main className="onboarding-page">
      <header className="onboarding-header">
        <BrandLockup priority />
        <div className="onboarding-identity">
          <Image src="/github-mark.svg" alt="" width={18} height={18} />
          <span>
            Signed in as <strong>maya-chen</strong>
          </span>
        </div>
      </header>

      <div className="onboarding-layout">
        <section className="onboarding-main" aria-labelledby="onboarding-title">
          <div className="onboarding-heading">
            <div>
              <p className="onboarding-eyebrow">{content.eyebrow}</p>
              <h1 id="onboarding-title">{content.title}</h1>
              <p>{content.description}</p>
            </div>
            <span
              className={`status-badge status-badge-${content.statusTone}`}
            >
              {content.statusLabel}
            </span>
          </div>

          <div className="installation-card">
            <div className="installation-card-header">
              <div>
                <span className="installation-label">Current installation</span>
                <strong>{content.installationOwner ?? "Not installed"}</strong>
              </div>
              <dl className="installation-count">
                <dt>Repositories</dt>
                <dd>
                  {content.repositoryCount === null
                    ? "—"
                    : content.repositoryCount}
                </dd>
              </dl>
            </div>

            <div className="installation-permissions">
              <span className="installation-label">Graphify can</span>
              <ul>
                <li>Read code and repository metadata you select</li>
                <li>Create branches and pull requests after your approval</li>
                <li>Receive repository events needed to keep graphs current</li>
              </ul>
            </div>

            <div className="onboarding-actions">
              <Link className="action-primary" href={content.primaryHref}>
                {content.primaryLabel}
              </Link>
              {content.secondaryLabel && content.secondaryHref && (
                <Link
                  className="action-secondary"
                  href={content.secondaryHref}
                >
                  {content.secondaryLabel}
                </Link>
              )}
            </div>
          </div>

          <div className="onboarding-notice">
            <span className="security-indicator" aria-hidden="true" />
            <p>{content.notice}</p>
          </div>
        </section>

        <aside className="onboarding-aside" aria-label="GitHub setup progress">
          <p className="onboarding-aside-label">Connection checklist</p>
          <ol>
            {SETUP_STEPS.map((step, index) => {
              const isComplete =
                index === 0 ||
                (index === 1 && content.state !== "not-installed") ||
                (index === 2 && content.state === "connected");

              return (
                <li className={isComplete ? "is-complete" : ""} key={step.label}>
                  <span>{isComplete ? "Done" : `0${index + 1}`}</span>
                  <div>
                    <strong>{step.label}</strong>
                    <p>{step.description}</p>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="onboarding-aside-help">
            <strong>Why a GitHub App?</strong>
            <p>
              It keeps repository permissions explicit, limited, and revocable
              from GitHub at any time.
            </p>
          </div>
        </aside>
      </div>
    </main>
  );
}
