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


async def test_launch_selects_the_extractor_role_of_the_unified_image(monkeypatch):
    """The one variable that decides which process the shared image starts.

    API, worker, and extractor run the same digest; SERVICE_ROLE is the only
    thing separating them. If this regressed to a missing value the image
    would refuse to boot (it has no default role), which is the intended
    fail-closed behaviour — but a regression to "api" or "worker" would be a
    privilege escalation, so pin it explicitly.
    """
    calls = []

    async def fake_graphql(_client, _token, query, variables):
        calls.append((query, variables))
        if "ServiceInstanceDeployV2" in query:
            return {"serviceInstanceDeployV2": "deployment-exact-id"}
        return {"variableCollectionUpsert": True}

    monkeypatch.setattr(sandbox, "get_settings", _settings)
    monkeypatch.setattr(sandbox.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(sandbox, "_graphql", fake_graphql)

    await sandbox.launch_project_on_railway(
        project_id="project-id",
        run_id="run-id",
        repo_url="https://github.com/o/r.git",
        default_branch="main",
        active_llm_provider="openai",
        active_llm_key="llm-secret",
        callback_secret="per-run-secret",
    )

    assert calls[0][1]["input"]["variables"]["SERVICE_ROLE"] == "extractor"


async def test_launch_never_hands_the_extractor_database_or_platform_secrets(monkeypatch):
    """The sandbox boundary, asserted as an allowlist.

    The extractor executes code paths driven by an untrusted repository. It
    reports results through an authenticated callback, so it needs no database
    at all — and a compromised extractor holding DATABASE_URL or
    RAILWAY_API_TOKEN would turn a contained incident into a full one.

    This is an exhaustive comparison rather than a handful of `not in` checks:
    a new variable added to the launch payload should have to be justified
    here, not merely avoid tripping a list of names someone thought of in 2026.
    """
    calls = []

    async def fake_graphql(_client, _token, query, variables):
        calls.append((query, variables))
        if "ServiceInstanceDeployV2" in query:
            return {"serviceInstanceDeployV2": "deployment-exact-id"}
        return {"variableCollectionUpsert": True}

    monkeypatch.setattr(sandbox, "get_settings", _settings)
    monkeypatch.setattr(sandbox.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(sandbox, "_graphql", fake_graphql)

    await sandbox.launch_project_on_railway(
        project_id="project-id",
        run_id="run-id",
        repo_url="https://github.com/o/r.git",
        default_branch="main",
        active_llm_provider="openai",
        active_llm_key="llm-secret",
        callback_secret="per-run-secret",
        repo_token="repo-secret",
    )

    payload = calls[0][1]["input"]
    variables = payload["variables"]

    assert set(variables) == {
        "SERVICE_ROLE",
        "REPO_URL",
        "REPO_BRANCH",
        "REPO_TOKEN",
        "PROJECT_ID",
        "RUN_ID",
        "WORKSPACE_STORAGE_TYPE",
        "GRAPHIFY_CALLBACK_URL",
        "GRAPHIFY_CALLBACK_SECRET",
        "OPENAI_API_KEY",
    }

    # replace=True is what makes the set above exhaustive rather than merely
    # additive: it clears the previous run's variables in the same call, so no
    # credential outlives the run it was minted for.
    assert payload["replace"] is True


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
