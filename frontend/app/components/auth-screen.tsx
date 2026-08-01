"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { BrandLockup } from "./brand-lockup";
import { fetchSession } from "../lib/session";

type AuthState = "checking-session" | "ready" | "redirecting" | "error";

type AuthScreenProps = {
  apiUrl: string | null;
};

const REDIRECT_DELAY_MS = 650;

export function AuthScreen({ apiUrl }: AuthScreenProps) {
  const router = useRouter();
  const [authState, setAuthState] = useState<AuthState>(
    apiUrl ? "checking-session" : "ready",
  );

  useEffect(() => {
    return () => {
      document.documentElement.classList.remove("auth-is-redirecting");
    };
  }, []);

  useEffect(() => {
    if (!apiUrl) {
      return;
    }

    let cancelled = false;

    fetchSession()
      .then((session) => {
        if (cancelled) return;
        if (session) {
          router.replace("/dashboard");
          return;
        }
        setAuthState("ready");
      })
      .catch(() => {
        // A failed session check (network/config issue) should not block
        // sign-in — fall back to showing the normal auth form.
        if (!cancelled) {
          setAuthState("ready");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [apiUrl, router]);

  function continueWithGitHub() {
    if (authState === "redirecting") {
      return;
    }

    if (!apiUrl) {
      setAuthState("error");
      return;
    }

    setAuthState("redirecting");
    document.documentElement.classList.add("auth-is-redirecting");

    window.setTimeout(() => {
      window.location.assign(`${apiUrl}/api/auth/github/login`);
    }, REDIRECT_DELAY_MS);
  }

  return (
    <main className="auth-page">
      <div className="auth-layout">
        <section className="auth-story" aria-labelledby="auth-story-title">
          <BrandLockup className="brand-lockup" priority />

          <div className="auth-story-copy">
            <p className="auth-eyebrow">GRAPH-AWARE ENGINEERING</p>
            <h1 id="auth-story-title">
              Understand, modify, and ship code with confidence.
            </h1>
            <p>
              One cloud workspace for exploring architecture, editing source,
              and turning agent proposals into reviewable pull requests.
            </p>
          </div>

          <div
            className="workspace-demo"
            role="img"
            aria-label="An animated Graphify workspace indexing a repository and preparing its architecture graph"
          >
            <div className="workspace-demo-header">
              <div>
                <span className="workspace-demo-kicker">Repository</span>
                <strong>graphify-labs / graphify</strong>
              </div>
              <span className="workspace-demo-status">
                <span aria-hidden="true" />
                Indexing
              </span>
            </div>

            <div className="workspace-demo-body">
              <div className="workspace-demo-files" aria-hidden="true">
                <span className="is-active">extract.py</span>
                <span>query.py</span>
                <span>graph.py</span>
                <span>server/app.py</span>
              </div>

              <div className="workspace-demo-graph" aria-hidden="true">
                <div className="demo-node demo-node-primary">
                  <small>function</small>
                  extract_codebase
                </div>
                <div className="demo-node demo-node-secondary">
                  <small>module</small>
                  graph.py
                </div>
                <div className="demo-node demo-node-tertiary">
                  <small>endpoint</small>
                  /api/extract
                </div>
              </div>

              <div className="workspace-demo-agent" aria-hidden="true">
                <span className="workspace-demo-kicker">Graph agent</span>
                <p>Mapped 1,284 relationships across 312 code nodes.</p>
                <span className="workspace-demo-ready">Architecture ready</span>
              </div>
            </div>

            <div className="workspace-demo-progress" aria-hidden="true">
              <span />
            </div>
          </div>

          <div className="auth-story-footnote">
            <strong>From repository to architecture in minutes.</strong>
            <span>No local setup. No API keys to manage.</span>
          </div>
        </section>

        <section className="auth-panel" aria-labelledby="auth-title">
          <div className="auth-form-wrap">
            <p className="auth-form-kicker">WELCOME TO GRAPHIFY</p>
            <h2 id="auth-title">Start with your GitHub account</h2>
            <p className="auth-form-intro">
              Connect the repositories you choose and launch a graph-aware
              engineering workspace.
            </p>

            <button
              className="github-button"
              type="button"
              onClick={continueWithGitHub}
              disabled={authState === "redirecting" || authState === "checking-session"}
              aria-describedby="github-permission-note"
            >
              <Image src="/github-mark.svg" alt="" width={20} height={20} />
              <span>
                {authState === "redirecting"
                  ? "Connecting to GitHub…"
                  : authState === "checking-session"
                    ? "Checking your session…"
                    : "Continue with GitHub"}
              </span>
              {(authState === "redirecting" || authState === "checking-session") && (
                <span className="button-spinner" aria-hidden="true" />
              )}
            </button>

            <p className="auth-permission-note" id="github-permission-note">
              Graphify only requests access to repositories you explicitly
              select. Your GitHub credentials never pass through this app.
            </p>

            {authState === "error" && (
              <div className="auth-error" role="alert">
                <strong>We could not reach the authentication service.</strong>
                <span>
                  Check the frontend API configuration, then try again.
                </span>
                <button type="button" onClick={() => setAuthState("ready")}>
                  Try again
                </button>
              </div>
            )}

            <div className="auth-security-note">
              <span className="security-indicator" aria-hidden="true" />
              <div>
                <strong>Secure GitHub App connection</strong>
                <span>
                  Repository permissions stay visible and revocable in GitHub.
                </span>
              </div>
            </div>
          </div>

          <p className="auth-footer">
            By continuing, you confirm that you are authorized to connect the
            selected repositories.
          </p>
        </section>
      </div>
    </main>
  );
}
