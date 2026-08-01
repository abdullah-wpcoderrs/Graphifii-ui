"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { logout } from "../lib/session";
import { useSessionContext } from "../lib/session-context";
import { Spinner } from "./ui";

export function SettingsScreen() {
  const router = useRouter();
  const { session, loading } = useSessionContext();
  const [signingOut, setSigningOut] = useState(false);

  async function handleLogout() {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      router.replace("/");
    }
  }

  if (loading || !session) {
    return (
      <div className="page-content page-content-centered">
        <Spinner size="lg" label="Loading your account" />
      </div>
    );
  }

  return (
    <div className="page-content">
      <header className="page-header">
        <h1>Settings</h1>
        <p>Account preferences and connection details.</p>
      </header>

      <section className="settings-section" aria-labelledby="settings-profile">
        <div className="settings-section-heading">
          <h2 id="settings-profile">Profile</h2>
          <p>Your identity comes from your connected GitHub account.</p>
        </div>
        <div className="settings-profile-card">
          {session.avatarUrl ? (
            <Image src={session.avatarUrl} alt="" width={56} height={56} />
          ) : (
            <div className="settings-profile-avatar-fallback" aria-hidden="true" />
          )}
          <div>
            <strong>{session.name || session.githubLogin}</strong>
            <span>@{session.githubLogin}</span>
            {session.email && <span>{session.email}</span>}
          </div>
        </div>
        <button
          className="ui-button ui-button-secondary ui-button-md settings-signout"
          type="button"
          disabled={signingOut}
          onClick={handleLogout}
        >
          <span className="ui-button-label">{signingOut ? "Signing out…" : "Sign out"}</span>
        </button>
      </section>

      <section className="settings-section" aria-labelledby="settings-workspace">
        <div className="settings-section-heading">
          <h2 id="settings-workspace">Workspace defaults</h2>
          <p>Coming soon — default branch behavior for new launches.</p>
        </div>
        <div className="settings-placeholder">
          <span>Not yet available</span>
        </div>
      </section>

      <section className="settings-section" aria-labelledby="settings-appearance">
        <div className="settings-section-heading">
          <h2 id="settings-appearance">Appearance</h2>
          <p>Coming soon — theme selection.</p>
        </div>
        <div className="settings-placeholder">
          <span>Not yet available</span>
        </div>
      </section>

      <section className="settings-section" aria-labelledby="settings-notifications">
        <div className="settings-section-heading">
          <h2 id="settings-notifications">Notifications</h2>
          <p>Coming soon — email alerts for extraction completion and failures.</p>
        </div>
        <div className="settings-placeholder">
          <span>Not yet available</span>
        </div>
      </section>

      <section className="settings-section is-danger" aria-labelledby="settings-danger">
        <div className="settings-section-heading">
          <h2 id="settings-danger">Danger zone</h2>
          <p>Coming soon — permanently delete your account and all projects.</p>
        </div>
        <div className="settings-placeholder">
          <span>Not yet available</span>
        </div>
      </section>
    </div>
  );
}
