"""Railway ephemeral job launch for sandbox provisioning.

Railway has no plain "run a one-off job with these env vars" endpoint —
everything goes through its GraphQL API
(https://backboard.railway.app/graphql/v2), and a service's environment
variables and its deploy trigger are two separate calls, not one. The shapes
below were confirmed by introspecting Railway's live schema on 2026-08-01
(the API can describe its own rules on request via a `__type` query) after
an earlier version, guessed from documentation prose, was rejected outright
by Railway's GraphQL validator. Concretely:

  1. variableCollectionUpsert(input: {...}) sets this deploy's env vars,
     with skipDeploys: true so setting them doesn't trigger a second,
     unwanted deploy on top of the explicit one below.
  2. serviceInstanceDeploy(serviceId, environmentId) triggers the deploy.
     It takes plain arguments, not a bundled `input` object, and returns
     nothing useful (a bare Boolean) — it does NOT hand back a deployment id.
  3. deployments(input: {...}, first: 1) is queried afterward to find the
     deployment that resulted, so Project.sandbox_id has something to record.
     This is best-effort tracking, not part of the critical path: if it
     comes back empty the deploy still happened, we just have no id for it.
"""

from __future__ import annotations

import httpx

from graphify.server.config import get_settings

RAILWAY_GRAPHQL_URL = "https://backboard.railway.app/graphql/v2"
_TIMEOUT = 30.0


class RailwayError(Exception):
    """Railway API responded, but rejected or could not complete the request."""


class RailwayNotConfiguredError(RailwayError):
    """RAILWAY_API_TOKEN (or the project/service/environment ids) is not set."""


class RailwayUnavailableError(RailwayError):
    """Railway could not be reached, or returned a server error."""


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
mutation ServiceInstanceDeploy($serviceId: String!, $environmentId: String!) {
  serviceInstanceDeploy(serviceId: $serviceId, environmentId: $environmentId)
}
"""

_LATEST_DEPLOYMENT = """
query LatestDeployment($input: DeploymentListInput!) {
  deployments(input: $input, first: 1) {
    edges { node { id status createdAt } }
  }
}
"""


async def launch_project_on_railway(
    project_id: str,
    repo_url: str,
    active_llm_provider: str,
    active_llm_key: str,
    repo_token: str | None = None,
) -> dict:
    """Trigger an ephemeral Railway job that clones repo_url and runs
    `graphify update /workspace` inside it. Returns
    {"id": <deployment id or None>} so Project.sandbox_id can be recorded.

    The job reports its own progress back to
    POST /api/internal/projects/{id}/status using SANDBOX_CALLBACK_SECRET;
    the WebSocket endpoint reads that persisted state rather than talking to
    Railway itself.

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
        "WORKSPACE_STORAGE_TYPE": settings.workspace_storage_type,
        # callback_base_url, not backend_url: in dev the container reaches us
        # through a tunnel while backend_url stays localhost for OAuth and
        # cookie purposes. See config.py.
        "GRAPHIFY_CALLBACK_URL": f"{settings.callback_base_url}/api/internal/projects/{project_id}/status",
        "GRAPHIFY_CALLBACK_SECRET": settings.sandbox_callback_secret or "",
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

        # Step 2: trigger the deploy. Returns a bare boolean, not an id.
        await _graphql(
            client,
            token,
            _TRIGGER_DEPLOY,
            {
                "serviceId": settings.railway_service_id,
                "environmentId": settings.railway_environment_id,
            },
        )

        # Step 3: best-effort lookup of the deployment that resulted, purely
        # so Project.sandbox_id has something to show in the UI. A failure
        # here must not fail the launch — the job is already running.
        deployment_id = None
        try:
            result = await _graphql(
                client,
                token,
                _LATEST_DEPLOYMENT,
                {
                    "input": {
                        "projectId": settings.railway_project_id,
                        "serviceId": settings.railway_service_id,
                        "environmentId": settings.railway_environment_id,
                    }
                },
            )
            edges = result.get("deployments", {}).get("edges", [])
            if edges:
                deployment_id = edges[0]["node"]["id"]
        except RailwayError:
            pass

    return {"id": deployment_id}
