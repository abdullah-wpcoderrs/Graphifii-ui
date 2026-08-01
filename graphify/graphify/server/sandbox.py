"""Railway ephemeral job launch for sandbox provisioning.

Railway has no plain "run a one-off job with these env vars" endpoint —
everything goes through its GraphQL API, and a service's environment
variables and its deploy trigger are two separate calls, not one. The shapes
below follow Railway's public API documentation as of 2026-08-01. Concretely:

  1. variableCollectionUpsert(input: {...}) sets this deploy's env vars,
     with skipDeploys: true so setting them doesn't trigger a second,
     unwanted deploy on top of the explicit one below.
  2. serviceInstanceDeployV2(serviceId, environmentId) triggers the deploy
     and returns its exact deployment id. The older Boolean mutation and
     "latest deployment" lookup are intentionally not used: they cannot
     safely correlate concurrent control-plane activity.
  3. deploymentCancel/deploymentStop terminate queued/building or running
     deployments by that exact id.
"""

from __future__ import annotations

import httpx

from graphify.server.config import get_settings

RAILWAY_GRAPHQL_URL = "https://backboard.railway.com/graphql/v2"
_TIMEOUT = 30.0


class RailwayError(Exception):
    """Railway API responded, but rejected or could not complete the request."""


class RailwayNotConfiguredError(RailwayError):
    """RAILWAY_API_TOKEN (or the project/service/environment ids) is not set."""


class RailwayUnavailableError(RailwayError):
    """Railway could not be reached, or returned a server error."""


class RailwayLaunchUncertainError(RailwayError):
    """The deploy trigger may have succeeded but no exact id was received."""


async def _graphql(client: httpx.AsyncClient, token: str, query: str, variables: dict) -> dict:
    try:
        response = await client.post(
            RAILWAY_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise RailwayUnavailableError(f"Railway API request failed: {exc}") from exc

    if response.status_code >= 500:
        raise RailwayUnavailableError(f"Railway returned {response.status_code}")

    data = response.json()
    if data.get("errors"):
        raise RailwayError(f"Railway rejected the request: {data['errors']}")
    return data.get("data", {})


_SET_VARIABLES = """
mutation VariableCollectionUpsert($input: VariableCollectionUpsertInput!) {
  variableCollectionUpsert(input: $input)
}
"""

_TRIGGER_DEPLOY = """
mutation ServiceInstanceDeployV2($serviceId: String!, $environmentId: String!) {
  serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId)
}
"""

_CANCEL_DEPLOYMENT = """
mutation DeploymentCancel($id: String!) {
  deploymentCancel(id: $id)
}
"""

_STOP_DEPLOYMENT = """
mutation DeploymentStop($id: String!) {
  deploymentStop(id: $id)
}
"""


async def launch_project_on_railway(
    project_id: str,
    run_id: str,
    repo_url: str,
    default_branch: str,
    active_llm_provider: str,
    active_llm_key: str,
    callback_secret: str,
    repo_token: str | None = None,
) -> dict:
    """Trigger an ephemeral Railway job that clones repo_url and runs
    `graphify update /workspace` inside it. Returns
    {"id": <deployment id>} so the run can be canceled and reconciled by
    exact identity.

    The job reports progress to the run-scoped callback URL using the random
    per-run credential supplied by the dispatcher; the WebSocket reads the
    persisted projection rather than talking to Railway itself.

    repo_token is the user's decrypted git provider token, needed to clone
    private repositories. It is passed as a job env var over Railway's HTTPS
    API, same as the LLM key.
    """
    settings = get_settings()
    if not settings.railway_configured:
        raise RailwayNotConfiguredError(
            "Railway sandbox provisioning is not configured — RAILWAY_API_TOKEN, "
            "RAILWAY_PROJECT_ID, RAILWAY_SERVICE_ID and RAILWAY_ENVIRONMENT_ID "
            "must all be set (see docs/railway-setup.md)"
        )

    env_vars = {
        "REPO_URL": repo_url,
        "PROJECT_ID": project_id,
        "RUN_ID": run_id,
        "REPO_BRANCH": default_branch,
        "WORKSPACE_STORAGE_TYPE": settings.workspace_storage_type,
        # callback_base_url, not backend_url: in dev the container reaches us
        # through a tunnel while backend_url stays localhost for OAuth and
        # cookie purposes. See config.py.
        "GRAPHIFY_CALLBACK_URL": (
            f"{settings.callback_base_url}/api/internal/projects/{project_id}/runs/{run_id}/status"
        ),
        "GRAPHIFY_CALLBACK_SECRET": callback_secret,
        f"{active_llm_provider.upper()}_API_KEY": active_llm_key,
    }
    if repo_token:
        env_vars["REPO_TOKEN"] = repo_token

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        token = settings.railway_api_token
        assert token is not None  # guaranteed by railway_configured above

        # Step 1: set this run's env vars. skipDeploys=True — the explicit
        # deploy trigger below is what actually starts the job; without this
        # flag Railway would also auto-deploy here, redundantly.
        await _graphql(
            client,
            token,
            _SET_VARIABLES,
            {
                "input": {
                    "projectId": settings.railway_project_id,
                    "environmentId": settings.railway_environment_id,
                    "serviceId": settings.railway_service_id,
                    "variables": env_vars,
                    "replace": True,
                    "skipDeploys": True,
                }
            },
        )

        # Step 2: trigger the deploy and capture its exact id atomically.
        try:
            result = await _graphql(
                client,
                token,
                _TRIGGER_DEPLOY,
                {
                    "serviceId": settings.railway_service_id,
                    "environmentId": settings.railway_environment_id,
                },
            )
        except RailwayError as exc:
            raise RailwayLaunchUncertainError(
                "Railway deploy trigger outcome is unknown; manual reconciliation is required"
            ) from exc

        deployment_id = result.get("serviceInstanceDeployV2")
        if not isinstance(deployment_id, str) or not deployment_id:
            raise RailwayLaunchUncertainError(
                "Railway triggered a deploy without returning its deployment id"
            )

    return {"id": deployment_id}


async def cancel_deployment_on_railway(deployment_id: str) -> None:
    """Cancel a queued/building deploy or stop it after it starts running."""
    settings = get_settings()
    if not settings.railway_configured:
        raise RailwayNotConfiguredError("Railway sandbox provisioning is not configured")

    token = settings.railway_api_token
    assert token is not None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            await _graphql(client, token, _CANCEL_DEPLOYMENT, {"id": deployment_id})
            return
        except RailwayError:
            try:
                await _graphql(client, token, _STOP_DEPLOYMENT, {"id": deployment_id})
                return
            except RailwayError as stop_error:
                raise RailwayError(
                    f"Railway could neither cancel nor stop deployment {deployment_id}"
                ) from stop_error


async def clear_sandbox_variables_on_railway() -> None:
    """Remove per-run credentials and repository inputs from shared config."""
    settings = get_settings()
    if not settings.railway_configured:
        raise RailwayNotConfiguredError("Railway sandbox provisioning is not configured")

    token = settings.railway_api_token
    assert token is not None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        await _graphql(
            client,
            token,
            _SET_VARIABLES,
            {
                "input": {
                    "projectId": settings.railway_project_id,
                    "environmentId": settings.railway_environment_id,
                    "serviceId": settings.railway_service_id,
                    "variables": {},
                    "replace": True,
                    "skipDeploys": True,
                }
            },
        )
