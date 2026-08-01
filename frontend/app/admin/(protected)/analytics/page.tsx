"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchAdminAnalytics, type AdminAnalytics } from "../../../lib/api";
import { ErrorState, Spinner } from "../../../components/ui";

const RANGE_OPTIONS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
  { label: "Last year", days: 365 },
];

function formatDuration(seconds: number | null) {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

function formatPercent(value: number | null) {
  if (value === null) return "—";
  return `${Math.round(value * 100)}%`;
}

export default function AdminAnalyticsPage() {
  const [days, setDays] = useState(30);
  const [analytics, setAnalytics] = useState<AdminAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchAdminAnalytics(days)
      .then(setAnalytics)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load analytics"));
  }, [days]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data load on mount/range change, not a synchronous render-time update
    load();
  }, [load]);

  return (
    <div className="page-content">
      <header className="page-header admin-page-header">
        <div>
          <h1>Analytics</h1>
          <p>Platform-wide signups, activity, and extraction outcomes.</p>
        </div>
        <label className="admin-range-select">
          <span>Range</span>
          <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
            {RANGE_OPTIONS.map((option) => (
              <option key={option.days} value={option.days}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && (
        <ErrorState title="Could not load analytics" description={error} onRetry={load} />
      )}

      {!error && !analytics && (
        <div className="page-content-centered">
          <Spinner size="lg" label="Loading analytics" />
        </div>
      )}

      {analytics && (
        <>
          <section className="admin-table-section">
            <h2>Users</h2>
            <section className="admin-stat-grid">
              <div className="admin-stat-card">
                <span>Total users</span>
                <strong>{analytics.users.total.toLocaleString()}</strong>
              </div>
              <div className="admin-stat-card">
                <span>New in range</span>
                <strong>{analytics.users.new_in_range.toLocaleString()}</strong>
              </div>
              <div className="admin-stat-card">
                <span>Active in range</span>
                <strong>{analytics.users.active_in_range.toLocaleString()}</strong>
              </div>
            </section>
          </section>

          <section className="admin-table-section">
            <h2>Projects</h2>
            <section className="admin-stat-grid">
              <div className="admin-stat-card">
                <span>Launched in range</span>
                <strong>{analytics.projects.launched_in_range.toLocaleString()}</strong>
              </div>
              <div className="admin-stat-card">
                <span>Success rate</span>
                <strong>{formatPercent(analytics.projects.success_rate)}</strong>
              </div>
              <div className="admin-stat-card">
                <span>Avg. indexing time</span>
                <strong>{formatDuration(analytics.projects.avg_indexing_seconds)}</strong>
              </div>
            </section>
          </section>

          <section className="admin-table-section">
            <h2>Status breakdown</h2>
            {Object.keys(analytics.projects.by_status).length === 0 ? (
              <p className="admin-empty-note">No projects launched in this range.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(analytics.projects.by_status).map(([status, count]) => (
                    <tr key={status}>
                      <td>{status}</td>
                      <td>{count.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
