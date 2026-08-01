from __future__ import annotations

from types import SimpleNamespace

import pytest

from graphify.server import sandbox


class _Client:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def _settings():
    return SimpleNamespace(
        railway_configured=True,
        railway_api_token="railway-token",
        railway_project_id="railway-project",
        railway_service_id="sandbox-service",
        railway_environment_id="production-env",
        workspace_storage_type="local",
        callback_base_url="https://api.example.test",
    )


async def test_launch_uses_exact_v2_deployment_id_and_run_scoped_inputs(monkeypatch):
    calls = []

    async def fake_graphql(_client, _token, query, variables):
        calls.append((query, variables))
        if "ServiceInstanceDeployV2" in query:
            return {"serviceInstanceDeployV2": "deployment-exact-id"}
        return {"variableCollectionUpsert": True}

    monkeypatch.setattr(sandbox, "get_settings", _settings)
    monkeypatch.setattr(sandbox.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(sandbox, "_graphql", fake_graphql)

    result = await sandbox.launch_project_on_railway(
        project_id="project-id",
        run_id="run-id",
        repo_url="https://github.com/o/r.git",
        default_branch="main",
        active_llm_provider="openai",
        active_llm_key="llm-secret",
        callback_secret="per-run-secret",
        repo_token="repo-secret",
    )

    assert result == {"id": "deployment-exact-id"}
    variables = calls[0][1]["input"]["variables"]
    assert variables["RUN_ID"] == "run-id"
    assert variables["GRAPHIFY_CALLBACK_SECRET"] == "per-run-secret"
    assert variables["GRAPHIFY_CALLBACK_URL"].endswith(
        "/api/internal/projects/project-id/runs/run-id/status"
    )
    assert "ServiceInstanceDeployV2" in calls[1][0]


async def test_cancel_falls_back_to_stop_for_running_deployment(monkeypatch):
    calls = []

    async def fake_graphql(_client, _token, query, variables):
        calls.append((query, variables))
        if "DeploymentCancel" in query:
            raise sandbox.RailwayError("already running")
        return {"deploymentStop": True}

    monkeypatch.setattr(sandbox, "get_settings", _settings)
    monkeypatch.setattr(sandbox.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(sandbox, "_graphql", fake_graphql)

    await sandbox.cancel_deployment_on_railway("deployment-id")

    assert "DeploymentCancel" in calls[0][0]
    assert "DeploymentStop" in calls[1][0]
    assert calls[1][1] == {"id": "deployment-id"}


async def test_launch_rejects_a_missing_deployment_id(monkeypatch):
    async def fake_graphql(_client, _token, _query, _variables):
        return {}

    monkeypatch.setattr(sandbox, "get_settings", _settings)
    monkeypatch.setattr(sandbox.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(sandbox, "_graphql", fake_graphql)

    with pytest.raises(sandbox.RailwayLaunchUncertainError, match="deployment id"):
        await sandbox.launch_project_on_railway(
            project_id="project-id",
            run_id="run-id",
            repo_url="https://github.com/o/r.git",
            default_branch="main",
            active_llm_provider="openai",
            active_llm_key="llm-secret",
            callback_secret="per-run-secret",
        )


async def test_clear_variables_replaces_shared_configuration_with_empty_map(monkeypatch):
    calls = []

    async def fake_graphql(_client, _token, query, variables):
        calls.append((query, variables))
        return {"variableCollectionUpsert": True}

    monkeypatch.setattr(sandbox, "get_settings", _settings)
    monkeypatch.setattr(sandbox.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(sandbox, "_graphql", fake_graphql)

    await sandbox.clear_sandbox_variables_on_railway()

    payload = calls[0][1]["input"]
    assert payload["variables"] == {}
    assert payload["replace"] is True
    assert payload["skipDeploys"] is True
