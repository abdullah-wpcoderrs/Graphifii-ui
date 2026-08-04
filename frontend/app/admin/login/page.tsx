"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { adminLogin, fetchAdminSession } from "../../lib/admin-session";
import { ApiError } from "../../lib/api-errors";
import { Button, Input, Spinner } from "../../components/ui";

type PageState = "checking" | "ready" | "submitting";

/** Every login failure used to render as "Invalid email or password", which
 * made a misconfigured deployment indistinguishable from a typo — a 503 from
 * an unset ADMIN_SESSION_SECRET, a CORS rejection, and a genuinely wrong
 * password all looked the same to whoever was staring at the screen. Only 401
 * is actually a credentials problem; everything else names its own cause. */
function loginErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) {
    return "Something went wrong signing in. Please try again.";
  }

  switch (err.code) {
    case "missing_api_url":
      return "This site is missing its backend URL (NEXT_PUBLIC_API_URL). Contact whoever deployed it.";
    case "network_error":
      // fetch() rejects identically for a down backend and for a response the
      // browser refused to expose (a CORS or cross-site-rejection failure), so
      // this message has to cover both. The browser console has the specifics.
      return "Could not reach the admin API. It may be down, or rejecting this site's origin.";
    case "session_not_persisted":
      return "Your credentials were accepted, but the browser rejected the session cookie. This is a backend cookie configuration problem, not a wrong password.";
  }

  if (err.status === 401) return "Invalid email or password.";
  if (err.status === 429) return "Too many failed attempts. Try again later.";
  // 503 carries a useful detail from the server ("admin authentication is not
  // configured …") — surfacing it verbatim is the whole point of this branch.
  if (err.status === 503) return err.message || "Admin sign-in is not configured on the server.";
  if (err.status >= 500) return "The admin API failed to handle the request. Check the server logs.";

  return err.message || "Something went wrong signing in. Please try again.";
}

export default function AdminLoginPage() {
  const router = useRouter();
  const [state, setState] = useState<PageState>("checking");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchAdminSession()
      .then((session) => {
        if (cancelled) return;
        if (session) {
          router.replace("/admin/settings");
          return;
        }
        setState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        // fetchAdminSession() turns a 401 into null rather than throwing, so
        // reaching here is never "just not logged in" — it is an unreachable
        // or misconfigured API. Say so now instead of letting the operator
        // type credentials into a form that cannot work.
        setError(loginErrorMessage(err));
        setState("ready");
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setState("submitting");

    try {
      await adminLogin(email, password);
      router.replace("/admin/settings");
    } catch (err) {
      setError(loginErrorMessage(err));
      setState("ready");
    }
  }

  if (state === "checking") {
    return (
      <div className="admin-login-page">
        <Spinner size="lg" label="Checking your session" />
      </div>
    );
  }

  return (
    <div className="admin-login-page">
      <div className="admin-login-panel">
        <h1>Admin sign in</h1>
        <p className="admin-login-intro">
          This is a separate login from GitHub — enter the email and password
          for your Graphify admin account.
        </p>

        {error && (
          <div className="page-banner is-error" role="alert">
            {error}
          </div>
        )}

        <form className="admin-login-form" onSubmit={handleSubmit}>
          <Input
            label="Email"
            type="email"
            name="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Input
            label="Password"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <Button type="submit" loading={state === "submitting"}>
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
