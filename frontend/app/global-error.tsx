"use client";

import Image from "next/image";
import Link from "next/link";

type GlobalErrorProps = {
  error: Error & { digest?: string };
  unstable_retry: () => void;
};

const styles = {
  body: {
    minHeight: "100vh",
    margin: 0,
    background: "#09090B",
    color: "#FFFFFF",
    fontFamily:
      'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  page: {
    display: "grid",
    minHeight: "100vh",
    placeItems: "center",
    padding: "24px",
    boxSizing: "border-box" as const,
  },
  shell: {
    width: "min(100%, 720px)",
    border: "1px solid #27272A",
    background: "#121215",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    minHeight: "58px",
    padding: "0 24px",
    borderBottom: "1px solid #27272A",
    fontSize: "18px",
    fontWeight: 650,
    letterSpacing: "-0.03em",
  },
  content: {
    padding: "clamp(34px, 7vw, 72px)",
  },
  code: {
    margin: "0 0 22px",
    color: "#3F3F46",
    fontFamily: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
    fontSize: "clamp(64px, 13vw, 112px)",
    fontWeight: 700,
    letterSpacing: "-0.08em",
    lineHeight: 0.8,
  },
  eyebrow: {
    margin: "0 0 12px",
    color: "#10B981",
    fontFamily: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
    fontSize: "11px",
    fontWeight: 600,
    letterSpacing: "0.13em",
  },
  title: {
    maxWidth: "560px",
    margin: 0,
    fontSize: "clamp(30px, 6vw, 48px)",
    fontWeight: 620,
    letterSpacing: "-0.045em",
    lineHeight: 1.04,
  },
  description: {
    maxWidth: "520px",
    margin: "20px 0 0",
    color: "#A1A1AA",
    fontSize: "14px",
    lineHeight: 1.65,
  },
  reference: {
    margin: "24px 0 0",
    color: "#71717A",
    fontFamily: 'ui-monospace, "SFMono-Regular", Consolas, monospace',
    fontSize: "11px",
  },
  actions: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: "10px",
    marginTop: "32px",
  },
  primary: {
    minHeight: "44px",
    padding: "0 18px",
    border: 0,
    borderRadius: "6px",
    background: "#10B981",
    color: "#06110D",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 650,
  },
  secondary: {
    display: "inline-flex",
    minHeight: "44px",
    alignItems: "center",
    padding: "0 18px",
    border: "1px solid #27272A",
    borderRadius: "6px",
    color: "#FFFFFF",
    fontSize: "13px",
    fontWeight: 600,
    textDecoration: "none",
  },
};

export default function GlobalError({
  error,
  unstable_retry,
}: GlobalErrorProps) {
  return (
    <html lang="en">
      <head>
        <title>Something went wrong — Graphify</title>
      </head>
      <body style={styles.body}>
        <main style={styles.page}>
          <section style={styles.shell} aria-labelledby="global-error-title">
            <div style={styles.header}>
              <Image
                src="/graphify-mark.png"
                alt=""
                width={28}
                height={28}
              />
              graphify
            </div>
            <div style={styles.content}>
              <p style={styles.code} aria-hidden="true">
                500
              </p>
              <p style={styles.eyebrow}>UNEXPECTED ERROR</p>
              <h1 id="global-error-title" style={styles.title}>
                Graphify hit an unexpected boundary.
              </h1>
              <p style={styles.description}>
                The application could not finish rendering this screen. Your
                repositories and workspace changes have not been modified.
              </p>
              {error.digest && (
                <p style={styles.reference}>Safe reference: {error.digest}</p>
              )}
              <div style={styles.actions}>
                <button style={styles.primary} onClick={unstable_retry}>
                  Try again
                </button>
                <Link style={styles.secondary} href="/">
                  Return to Graphify
                </Link>
              </div>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
