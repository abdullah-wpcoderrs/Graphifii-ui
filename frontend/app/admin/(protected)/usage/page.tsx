"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchAdminUsage, type AdminUsageSummary } from "../../../lib/api";
import { ErrorState, Spinner } from "../../../components/ui";

const RANGE_OPTIONS = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
  { label: "Last year", days: 365 },
];

function formatCost(value: number) {
  return `$${value.toFixed(2)}`;
}

export default function AdminUsagePage() {
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<AdminUsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchAdminUsage(days)
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load usage"));
  }, [days]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data load on mount/range change, not a synchronous render-time update
    load();
  }, [load]);

  return (
    <div className="page-content">
      <header className="page-header admin-page-header">
        <div>
          <h1>Usage & Spend</h1>
          <p>LLM spend across every provider, broken down by provider and by user.</p>
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
        <ErrorState title="Could not load usage" description={error} onRetry={load} />
      )}

      {!error && !summary && (
        <div className="page-content-centered">
          <Spinner size="lg" label="Loading usage" />
        </div>
      )}

      {summary && (
        <>
          <section className="admin-stat-grid">
            <div className="admin-stat-card">
              <span>Total spend</span>
              <strong>{formatCost(summary.totals.cost_estimate)}</strong>
            </div>
            <div className="admin-stat-card">
              <span>Calls</span>
              <strong>{summary.totals.calls.toLocaleString()}</strong>
            </div>
            <div className="admin-stat-card">
              <span>Prompt tokens</span>
              <strong>{summary.totals.prompt_tokens.toLocaleString()}</strong>
            </div>
            <div className="admin-stat-card">
              <span>Completion tokens</span>
              <strong>{summary.totals.completion_tokens.toLocaleString()}</strong>
            </div>
          </section>

          <section className="admin-table-section">
            <h2>By provider</h2>
            {summary.by_provider.length === 0 ? (
              <p className="admin-empty-note">No spend recorded in this range.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Calls</th>
                    <th>Prompt tokens</th>
                    <th>Completion tokens</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_provider.map((row) => (
                    <tr key={row.provider}>
                      <td>{row.provider}</td>
                      <td>{row.calls.toLocaleString()}</td>
                      <td>{row.prompt_tokens.toLocaleString()}</td>
                      <td>{row.completion_tokens.toLocaleString()}</td>
                      <td>{formatCost(row.cost_estimate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="admin-table-section">
            <h2>By user</h2>
            {summary.by_user.length === 0 ? (
              <p className="admin-empty-note">No spend recorded in this range.</p>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Calls</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_user.map((row) => (
                    <tr key={row.user_id ?? row.github_login}>
                      <td>{row.github_login}</td>
                      <td>{row.calls.toLocaleString()}</td>
                      <td>{formatCost(row.cost_estimate)}</td>
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
