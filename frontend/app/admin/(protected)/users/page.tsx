"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteAdminUser,
  fetchAdminUsers,
  updateAdminUser,
  type AdminUserSummary,
} from "../../../lib/api";
import { Badge, ErrorState, Spinner } from "../../../components/ui";

const PAGE_SIZE = 50;

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function IntegrationDots({ integrations }: { integrations: AdminUserSummary["integrations"] }) {
  const connected = Object.entries(integrations)
    .filter(([, value]) => value)
    .map(([key]) => key);

  if (connected.length === 0) {
    return <span className="admin-empty-note">None</span>;
  }

  return <span>{connected.join(", ")}</span>;
}

export default function AdminUsersPage() {
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [users, setUsers] = useState<AdminUserSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchAdminUsers(PAGE_SIZE, offset)
      .then((result) => {
        setUsers(result.users);
        setTotal(result.total);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load users"));
  }, [offset]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data load on mount/page change, not a synchronous render-time update
    load();
  }, [load]);

  async function handleToggleActive(user: AdminUserSummary) {
    setPendingId(user.id);
    try {
      await updateAdminUser(user.id, !user.is_active);
      setUsers((current) =>
        current
          ? current.map((row) => (row.id === user.id ? { ...row, is_active: !row.is_active } : row))
          : current,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update this user");
    } finally {
      setPendingId(null);
    }
  }

  async function handleDelete(user: AdminUserSummary) {
    setPendingId(user.id);
    try {
      await deleteAdminUser(user.id);
      setUsers((current) => (current ? current.filter((row) => row.id !== user.id) : current));
      setTotal((current) => Math.max(0, current - 1));
      setConfirmDeleteId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete this user");
    } finally {
      setPendingId(null);
    }
  }

  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className="page-content">
      <header className="page-header">
        <h1>Users</h1>
        <p>Every account with a Graphify session, their connected providers, and their standing.</p>
      </header>

      {error && <ErrorState title="Could not load users" description={error} onRetry={load} />}

      {!error && !users && (
        <div className="page-content-centered">
          <Spinner size="lg" label="Loading users" />
        </div>
      )}

      {users && (
        <section className="admin-table-section">
          {users.length === 0 ? (
            <p className="admin-empty-note">No users yet.</p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Projects</th>
                  <th>Integrations</th>
                  <th>Status</th>
                  <th>Joined</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.github_login}</strong>
                      {user.email && <div className="admin-table-subtext">{user.email}</div>}
                    </td>
                    <td>{user.role}</td>
                    <td>{user.project_count}</td>
                    <td>
                      <IntegrationDots integrations={user.integrations} />
                    </td>
                    <td>
                      <Badge tone={user.is_active ? "success" : "danger"}>
                        {user.is_active ? "Active" : "Suspended"}
                      </Badge>
                    </td>
                    <td>{formatDate(user.created_at)}</td>
                    <td className="admin-table-actions">
                      {confirmDeleteId === user.id ? (
                        <span className="admin-confirm-delete">
                          <span>Delete this user and all their projects?</span>
                          <button
                            type="button"
                            className="admin-action-danger"
                            disabled={pendingId === user.id}
                            onClick={() => handleDelete(user)}
                          >
                            {pendingId === user.id ? "Deleting…" : "Confirm"}
                          </button>
                          <button type="button" onClick={() => setConfirmDeleteId(null)}>
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <>
                          <button
                            type="button"
                            disabled={pendingId === user.id}
                            onClick={() => handleToggleActive(user)}
                          >
                            {user.is_active ? "Suspend" : "Reactivate"}
                          </button>
                          <button
                            type="button"
                            className="admin-action-danger"
                            disabled={pendingId === user.id}
                            onClick={() => setConfirmDeleteId(user.id)}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="admin-pagination">
            <span>
              Showing {users.length === 0 ? 0 : offset + 1}–{offset + users.length} of {total}
            </span>
            <div>
              <button type="button" disabled={!hasPrev} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}>
                Previous
              </button>
              <button type="button" disabled={!hasNext} onClick={() => setOffset((value) => value + PAGE_SIZE)}>
                Next
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
