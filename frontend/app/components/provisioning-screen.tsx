"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { PROVISIONING_PHASES } from "../lib/workspace-fixtures";
import { BrandLockup } from "./brand-lockup";

type ProvisioningScreenProps = {
  initialFailure: boolean;
  projectId: string;
};

type ProvisioningStatus = "running" | "failed" | "ready";

function formatElapsed(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${remainder
    .toString()
    .padStart(2, "0")}`;
}

export function ProvisioningScreen({
  initialFailure,
  projectId,
}: ProvisioningScreenProps) {
  const router = useRouter();
  const [status, setStatus] = useState<ProvisioningStatus>(
    initialFailure ? "failed" : "running",
  );
  const [phaseIndex, setPhaseIndex] = useState(initialFailure ? 3 : 0);
  const [elapsed, setElapsed] = useState(initialFailure ? 47 : 0);
  const latestSequence = useRef(initialFailure ? 3 : 0);
  const currentPhase = PROVISIONING_PHASES[phaseIndex];
  const redirecting = status === "ready";

  useEffect(() => {
    if (status !== "running") return;

    const elapsedTimer = window.setInterval(() => {
      setElapsed((value) => value + 1);
    }, 1000);

    const phaseTimer = window.setInterval(() => {
      const nextSequence = latestSequence.current + 1;

      if (nextSequence >= PROVISIONING_PHASES.length) {
        setStatus("ready");
        window.clearInterval(phaseTimer);
        return;
      }

      latestSequence.current = nextSequence;
      setPhaseIndex(nextSequence);
    }, 1250);

    return () => {
      window.clearInterval(elapsedTimer);
      window.clearInterval(phaseTimer);
    };
  }, [status]);

  useEffect(() => {
    if (status !== "ready") return;

    const redirectTimer = window.setTimeout(() => {
      router.push(`/workspace/${projectId}`);
    }, 1200);

    return () => window.clearTimeout(redirectTimer);
  }, [projectId, router, status]);

  const visibleEvents = useMemo(
    () => PROVISIONING_PHASES.slice(0, phaseIndex + 1).reverse(),
    [phaseIndex],
  );

  function retry() {
    latestSequence.current = 0;
    setPhaseIndex(0);
    setElapsed(0);
    setStatus("running");
  }

  return (
    <main className="provisioning-page">
      <header className="provisioning-header">
        <BrandLockup priority />
        <Link href="/dashboard">Back to repositories</Link>
      </header>

      <div className="provisioning-shell">
        <section
          className="provisioning-main"
          aria-labelledby="provisioning-title"
        >
          <div className="provisioning-repository">
            <span className="provisioning-repository-mark" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <div>
              <span>Graphify-Labs</span>
              <strong>graphify</strong>
            </div>
            <code>main</code>
          </div>

          {status === "failed" ? (
            <div className="provisioning-failure" role="alert">
              <p className="provisioning-eyebrow">Extraction interrupted</p>
              <h1 id="provisioning-title">Parsing stopped on a source file.</h1>
              <p>
                The sandbox is still isolated, but Graphify has not persisted
                partial graph artifacts. Retry the extraction or return to the
                dashboard.
              </p>
              <dl>
                <div>
                  <dt>Failed phase</dt>
                  <dd>Parsing source files</dd>
                </div>
                <div>
                  <dt>Safe reference</dt>
                  <dd>EXT-8FA2</dd>
                </div>
              </dl>
              <div className="provisioning-actions">
                <button type="button" onClick={retry}>
                  Retry extraction
                </button>
                <Link href="/dashboard">Return to dashboard</Link>
              </div>
            </div>
          ) : (
            <>
              <div className="provisioning-heading">
                <div>
                  <p className="provisioning-eyebrow">
                    {status === "ready"
                      ? "Workspace ready"
                      : "Provisioning workspace"}
                  </p>
                  <h1 id="provisioning-title">{currentPhase.label}</h1>
                  <p>{currentPhase.description}</p>
                </div>
                <strong className="provisioning-percent">
                  {currentPhase.progress}
                  <span>%</span>
                </strong>
              </div>

              <div
                className="provisioning-progress"
                role="progressbar"
                aria-label="Workspace provisioning progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={currentPhase.progress}
              >
                <span style={{ width: `${currentPhase.progress}%` }} />
              </div>

              <ol className="provisioning-phases">
                {PROVISIONING_PHASES.map((phase, index) => {
                  const isComplete = index < phaseIndex || status === "ready";
                  const isActive = index === phaseIndex && status !== "ready";

                  return (
                    <li
                      className={`${isComplete ? "is-complete" : ""} ${
                        isActive ? "is-active" : ""
                      }`}
                      key={phase.id}
                    >
                      <span>{isComplete ? "✓" : index + 1}</span>
                      <div>
                        <strong>{phase.label}</strong>
                        <p>{phase.description}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>

              {redirecting && (
                <p className="provisioning-redirect" role="status">
                  Opening the workspace…
                </p>
              )}
            </>
          )}
        </section>

        <aside className="provisioning-aside" aria-label="Provisioning events">
          <div className="provisioning-aside-header">
            <div>
              <span>Event log</span>
              <strong>{status === "failed" ? "Paused" : "Live"}</strong>
            </div>
            <dl>
              <dt>Elapsed</dt>
              <dd>{formatElapsed(elapsed)}</dd>
            </dl>
          </div>

          <div className="provisioning-events" aria-live="polite">
            {visibleEvents.map((phase, index) => (
              <article key={phase.id}>
                <span className={index === 0 ? "is-current" : ""} />
                <div>
                  <time>{formatElapsed(Math.max(0, elapsed - index * 7))}</time>
                  <p>{phase.event}</p>
                </div>
              </article>
            ))}
          </div>

          <p className="provisioning-note">
            This view uses contract fixtures until the Railway WebSocket route
            is available. Terminal states are handled exactly once.
          </p>
        </aside>
      </div>
    </main>
  );
}
