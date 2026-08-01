"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { adminLogin, fetchAdminSession } from "../../lib/admin-session";
import { ApiError } from "../../lib/api-errors";
import { Button, Input, Spinner } from "../../components/ui";

type PageState = "checking" | "ready" | "submitting";

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
      .catch(() => {
        if (!cancelled) setState("ready");
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
      setError(
        err instanceof ApiError && err.status === 429
          ? "Too many failed attempts. Try again later."
          : "Invalid email or password.",
      );
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
