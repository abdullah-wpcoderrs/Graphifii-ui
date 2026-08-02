"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  cancelProject,
  fetchProject,
  launchProject,
  type LaunchProgress,
  type Project,
  type ProjectStatus,
} from "../lib/api";
import { getPublicWsUrl } from "../lib/env";
import { BrandLockup } from "./brand-lockup";

type ProvisioningScreenProps = {
  initialFailure: boolean;
  projectId: string;
};

type ConnectionState = "connecting" | "open" | "closed";

type TimelineEvent = {
  id: string;
  at: number;
  label: string;
};

const STATUS_PHASES: {
  id: ProjectStatus;
  label: string;
  description: string;
}[] = [
  {
    id: "CLONING",
    label: "Cloning repository",
    description: "Fetching the repository into an isolated sandbox.",
  },
  {
    id: "INDEXING",
    label: "Building the graph",
    description: "Parsing source, extracting symbols, calls, and communities.",
  },
];

const MAX_BACKOFF_MS = 10_000;
const READY_REDIRECT_DELAY_MS = 1200;

function formatElapsed(ms: number) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds
    .toString()
    .padStart(2, "0")}`;
}

export function ProvisioningScreen({ projectId }: ProvisioningScreenProps) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [progress, setProgress] = useState<LaunchProgress | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [retrying, setRetrying] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const [startedAt, setStartedAt] = useState(() => Date.now());
  const socketRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const backoffRef = useRef(1000);
  const mountedRef = useRef(true);
  const redirectedRef = useRef(false);
  const lastStatusRef = useRef<ProjectStatus | null>(null);
  const lastMessageRef = useRef<string | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    fetchProject(projectId)
      .then((value) => {
        if (mountedRef.current) setProject(value);
      })
      .catch(() => {
        // Non-fatal — the header falls back to a generic label.
      });
  }, [projectId, attempt]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  function appendEvent(label: string) {
    setEvents((current) =>
      [{ id: `${Date.now()}-${current.length}`, at: Date.now(), label }, ...current].slice(
        0,
        40,
      ),
    );
  }

  useEffect(() => {
    const wsBase = getPublicWsUrl();
    if (!wsBase) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- config validation on mount, not a synchronous render-time update
      setFatalError("The backend API URL is not configured.");
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      setConnection("connecting");
      const socket = new WebSocket(`${wsBase}/ws/projects/${projectId}`);
      socketRef.current = socket;

      socket.onopen = () => {
        if (cancelled) return;
        setConnection("open");
        backoffRef.current = 1000;
      };

      socket.onmessage = (event) => {
        if (cancelled) return;
        let payload: LaunchProgress;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return; // Ignore a malformed frame rather than tearing down the connection.
        }

        if (payload.status !== lastStatusRef.current) {
          appendEvent(payload.message ?? `Status changed to ${payload.status}`);
        } else if (payload.message && payload.message !== lastMessageRef.current) {
          appendEvent(payload.message);
        }
        lastStatusRef.current = payload.status;
        lastMessageRef.current = payload.message;
        setProgress(payload);
      };

      socket.onclose = (event) => {
        if (cancelled) return;
        setConnection("closed");

        if (event.code === 4401) {
          setFatalError("Your session has expired. Sign in again to continue.");
          return;
        }
        if (event.code === 4403) {
          setFatalError("Your account has been suspended.");
          return;
        }
        if (event.code === 4404) {
          setFatalError("This project no longer exists.");
          return;
        }
        // A normal close after a terminal payload (READY/FAILED) is expected
        // server behavior, not a dropped connection — don't reconnect for it.
        if (event.code === 1000) return;

        const delay = Math.min(backoffRef.current, MAX_BACKOFF_MS);
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);
        retryTimerRef.current = window.setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (retryTimerRef.current) window.clearTimeout(retryTimerRef.current);
      socketRef.current?.close(1000);
      socketRef.current = null;
    };
  }, [projectId, attempt]);

  useEffect(() => {
    if (!progress || progress.status !== "READY" || redirectedRef.current) return;
    redirectedRef.current = true;
    const timer = window.setTimeout(() => {
      router.push(`/workspace/${projectId}`);
    }, READY_REDIRECT_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [progress, projectId, router]);

  async function handleCancel() {
    setCanceling(true);
    try {
      await cancelProject(projectId);
    } catch {
      // The WebSocket stream reflects the real outcome either way.
    } finally {
      setCanceling(false);
    }
  }

  async function handleRetry() {
    if (!project) return;
    setRetrying(true);
    try {
      await launchProject({
        repoFullName: project.repo_name,
        repoUrl: project.repo_url,
        provider: project.provider,
        defaultBranch: project.default_branch,
      });
      setEvents([]);
      backoffRef.current = 1000;
      redirectedRef.current = false;
      lastStatusRef.current = null;
      lastMessageRef.current = null;
      setStartedAt(Date.now());
      // The WS connection closed after the prior terminal FAILED frame —
      // bump attempt to force the effect above to open a fresh socket.
      setAttempt((value) => value + 1);
    } catch (error) {
      setFatalError(
        error instanceof Error ? error.message : "Could not restart the extraction.",
      );
    } finally {
      setRetrying(false);
    }
  }

  const elapsed = now - startedAt;
  const owner = project?.repo_name.split("/")[0] ?? null;
  const name = project?.repo_name.split("/").slice(1).join("/") ?? null;

  const phaseIndex = progress
    ? STATUS_PHASES.findIndex((phase) => phase.id === progress.status)
    : -1;
  const currentPhase =
    phaseIndex >= 0 ? STATUS_PHASES[phaseIndex] : STATUS_PHASES[0];
  const isFailed = progress?.status === "FAILED";
  const isReady = progress?.status === "READY";
  const isRunning = Boolean(progress) && !isFailed && !isReady;
  const displayPercent = progress?.progress_percent ?? 0;

  return (
    <main className="provisioning-page">
      <header className="provisioning-header">
        <BrandLockup priority />
        <Link href="/repositories">Back to repositories</Link>
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
              <span>{owner ?? "Loading repository…"}</span>
              <strong>{name ?? ""}</strong>
            </div>
          </div>

          {fatalError ? (
            <div className="provisioning-failure" role="alert">
              <p className="provisioning-eyebrow">Connection lost</p>
              <h1 id="provisioning-title">{fatalError}</h1>
              <div className="provisioning-actions">
                <Link href="/repositories">Return to repositories</Link>
              </div>
            </div>
          ) : isFailed ? (
            <div className="provisioning-failure" role="alert">
              <p className="provisioning-eyebrow">Extraction interrupted</p>
              <h1 id="provisioning-title">
                {progress?.error ?? "Extraction stopped before it finished."}
              </h1>
              <p>
                The sandbox is isolated and no partial graph artifacts were
                persisted. Retry the extraction or return to repositories.
              </p>
              {progress?.message && (
                <dl>
                  <div>
                    <dt>Last status</dt>
                    <dd>{progress.message}</dd>
                  </div>
                </dl>
              )}
              <div className="provisioning-actions">
                <button
                  type="button"
                  disabled={retrying || !project}
                  onClick={handleRetry}
                >
                  {retrying ? "Retrying…" : "Retry extraction"}
                </button>
                <Link href="/repositories">Return to repositories</Link>
              </div>
            </div>
          ) : !progress ? (
            <div className="provisioning-heading">
              <div>
                <p className="provisioning-eyebrow">Connecting</p>
                <h1 id="provisioning-title">Connecting to the sandbox…</h1>
                <p>Waiting for the first progress update.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="provisioning-heading">
                <div>
                  <p className="provisioning-eyebrow">
                    {isReady ? "Workspace ready" : "Provisioning workspace"}
                  </p>
                  <h1 id="provisioning-title">
                    {progress.message ?? currentPhase.label}
                  </h1>
                  <p>{currentPhase.description}</p>
                </div>
                <strong className="provisioning-percent">
                  {displayPercent}
                  <span>%</span>
                </strong>
              </div>

              <div
                className="provisioning-progress"
                role="progressbar"
                aria-label="Workspace provisioning progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={displayPercent}
              >
                <span style={{ width: `${displayPercent}%` }} />
              </div>

              <ol className="provisioning-phases">
                {STATUS_PHASES.map((phase, index) => {
                  const isComplete = index < phaseIndex || isReady;
                  const isActive = index === phaseIndex && !isReady;

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

              {isRunning && (
                <div className="provisioning-actions">
                  <button
                    type="button"
                    disabled={canceling}
                    onClick={handleCancel}
                  >
                    {canceling ? "Canceling…" : "Cancel"}
                  </button>
                </div>
              )}

              {isReady && (
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
              <strong>
                {isFailed || fatalError
                  ? "Paused"
                  : connection === "open"
                    ? "Live"
                    : "Reconnecting…"}
              </strong>
            </div>
            <dl>
              <dt>Elapsed</dt>
              <dd>{formatElapsed(elapsed)}</dd>
            </dl>
          </div>

          <div className="provisioning-events" aria-live="polite">
            {events.length === 0 ? (
              <p className="provisioning-note">Waiting for the first event…</p>
            ) : (
              events.map((item, index) => (
                <article key={item.id}>
                  <span className={index === 0 ? "is-current" : ""} />
                  <div>
                    <time>{formatElapsed(item.at - startedAt)}</time>
                    <p>{item.label}</p>
                  </div>
                </article>
              ))
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}
