"""Reading and writing repository files through provider APIs — no clone.

This is what lets the agent run in the main backend process instead of a
sandbox. Every operation the PR flow needs (read a file, create a branch,
commit a set of files, open a pull request) has a REST equivalent on all
three providers, so there is never a working directory on disk: no clone
time, no disk usage, and no idle container between a user's messages.

The commit path deliberately uses GitHub's **Git Data API** (blob → tree →
commit → ref) rather than the simpler Contents API. The Contents API writes
one file per call, which means an N-file change lands as N separate commits
and a failure halfway through leaves the branch in a state the user never
approved. The Git Data path builds the whole tree first and moves the branch
ref exactly once, so a multi-file change is atomic. GitLab gets the same
property for free from its commits API, which takes a list of actions.

Conflict handling: callers pass the blob sha they read a file at. Before
committing, the current sha on the base branch is re-read and compared. A
mismatch means the file moved underneath the agent, and the commit is
refused rather than silently reverting whoever else changed it.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import quote

import httpx

_TIMEOUT = 20.0

# A single source file the agent might read. Well beyond any reasonable
# source file, small enough that a mistargeted path (a checked-in binary, a
# vendored bundle) cannot pull hundreds of MB into a prompt.
MAX_FILE_BYTES = 1024 * 1024


class RepoError(Exception):
    """A repository operation failed."""


class RepoAuthError(RepoError):
    """The stored token was rejected — expired, revoked, or missing a scope."""


class RepoNotFoundError(RepoError):
    """The repository, branch, or file does not exist."""


class RepoConflictError(RepoError):
    """The remote moved since the agent read it, or the branch already exists."""


class RepoTooLargeError(RepoError):
    """The file exceeds MAX_FILE_BYTES."""


@dataclass
class FileContent:
    path: str
    content: str
    sha: str | None
    size: int


@dataclass
class FileChange:
    """One file to write. before_sha is the blob sha it was read at."""

    path: str
    content: str
    before_sha: str | None


@dataclass
class PullRequestResult:
    number: int
    url: str
    branch: str


def _decode_blob(raw: str, encoding: str) -> str:
    if encoding == "base64":
        data = base64.b64decode(raw)
    else:
        data = raw.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise RepoTooLargeError(f"file exceeds the {MAX_FILE_BYTES // 1024}KB limit")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepoError("file is not valid UTF-8 text (binary files are not supported)") from exc


class GitHubRepoClient:
    """Repository operations against GitHub's REST API.

    Also serves GitBucket, which implements the same API shape under
    /api/v3 with a `token` rather than `Bearer` authorization scheme — see
    GitBucketRepoClient below, which is this class with those two knobs
    changed. Any behavior added here must therefore stay within the subset
    GitBucket actually implements, or be overridden there.
    """

    api_base = "https://api.github.com"
    auth_scheme = "Bearer"

    def __init__(self, token: str, repo_full_name: str) -> None:
        self._token = token
        self._repo = repo_full_name.strip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"{self.auth_scheme} {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _url(self, path: str) -> str:
        return f"{self.api_base}/repos/{self._repo}{path}"

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = await client.request(method, self._url(path), headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise RepoError(f"could not reach the git provider: {exc}") from exc

        if response.status_code in (401, 403):
            raise RepoAuthError(
                "the stored git token was rejected — reconnect the integration"
            )
        if response.status_code == 404:
            raise RepoNotFoundError("repository, branch, or file not found")
        if response.status_code == 409:
            raise RepoConflictError("the repository changed since this was prepared")
        if response.status_code >= 500:
            raise RepoError(f"the git provider returned {response.status_code}")
        return response

    async def get_file(self, path: str, ref: str) -> FileContent:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request(
                client, "GET", f"/contents/{quote(path)}", params={"ref": ref}
            )
        if response.status_code != 200:
            raise RepoError(f"could not read {path} ({response.status_code})")

        data = response.json()
        if isinstance(data, list):
            raise RepoError(f"{path} is a directory, not a file")
        if data.get("size", 0) > MAX_FILE_BYTES:
            raise RepoTooLargeError(f"{path} exceeds the {MAX_FILE_BYTES // 1024}KB limit")

        return FileContent(
            path=path,
            content=_decode_blob(data.get("content", ""), data.get("encoding", "base64")),
            sha=data.get("sha"),
            size=data.get("size", 0),
        )

    async def _branch_head_sha(self, client: httpx.AsyncClient, branch: str) -> str:
        response = await self._request(client, "GET", f"/git/ref/heads/{quote(branch, safe='')}")
        if response.status_code != 200:
            raise RepoNotFoundError(f"branch {branch!r} not found")
        return response.json()["object"]["sha"]

    async def create_branch(self, base_branch: str, new_branch: str) -> str:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            base_sha = await self._branch_head_sha(client, base_branch)
            response = await self._request(
                client,
                "POST",
                "/git/refs",
                json={"ref": f"refs/heads/{new_branch}", "sha": base_sha},
            )
        if response.status_code == 422:
            raise RepoConflictError(f"branch {new_branch!r} already exists")
        if response.status_code not in (200, 201):
            raise RepoError(f"could not create branch {new_branch!r} ({response.status_code})")
        return base_sha

    async def _assert_no_conflicts(
        self, client: httpx.AsyncClient, changes: list[FileChange], ref: str
    ) -> None:
        """Refuse the commit if any file moved since the agent read it."""
        for change in changes:
            response = await self._request(
                client, "GET", f"/contents/{quote(change.path)}", params={"ref": ref}
            )
            current_sha = response.json().get("sha") if response.status_code == 200 else None

            if change.before_sha is None:
                # Agent is creating the file; someone else creating it first
                # is a conflict.
                if current_sha is not None:
                    raise RepoConflictError(
                        f"{change.path} now exists on the remote — regenerate the change"
                    )
            elif current_sha != change.before_sha:
                raise RepoConflictError(
                    f"{change.path} changed on the remote since this was prepared — "
                    "regenerate the change"
                )

    async def commit_files(
        self, branch: str, changes: list[FileChange], message: str, *, base_branch: str
    ) -> str:
        """Atomically write every change as one commit on `branch`."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await self._assert_no_conflicts(client, changes, base_branch)

            parent_sha = await self._branch_head_sha(client, branch)
            commit_response = await self._request(client, "GET", f"/git/commits/{parent_sha}")
            if commit_response.status_code != 200:
                raise RepoError("could not read the branch's current commit")
            base_tree = commit_response.json()["tree"]["sha"]

            tree_entries = []
            for change in changes:
                blob_response = await self._request(
                    client, "POST", "/git/blobs", json={"content": change.content, "encoding": "utf-8"}
                )
                if blob_response.status_code not in (200, 201):
                    raise RepoError(f"could not write {change.path} ({blob_response.status_code})")
                tree_entries.append(
                    {
                        "path": change.path,
                        # 100644 = regular non-executable file. Preserving an
                        # existing file's real mode would need a tree read per
                        # path; the agent only edits source files.
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_response.json()["sha"],
                    }
                )

            tree_response = await self._request(
                client, "POST", "/git/trees", json={"base_tree": base_tree, "tree": tree_entries}
            )
            if tree_response.status_code not in (200, 201):
                raise RepoError(f"could not build the commit tree ({tree_response.status_code})")

            new_commit = await self._request(
                client,
                "POST",
                "/git/commits",
                json={
                    "message": message,
                    "tree": tree_response.json()["sha"],
                    "parents": [parent_sha],
                },
            )
            if new_commit.status_code not in (200, 201):
                raise RepoError(f"could not create the commit ({new_commit.status_code})")
            commit_sha = new_commit.json()["sha"]

            ref_response = await self._request(
                client,
                "PATCH",
                f"/git/refs/heads/{quote(branch, safe='')}",
                json={"sha": commit_sha},
            )
            if ref_response.status_code != 200:
                raise RepoError(f"could not move branch {branch!r} ({ref_response.status_code})")

        return commit_sha

    async def open_pull_request(
        self, *, title: str, body: str, head: str, base: str
    ) -> PullRequestResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request(
                client, "POST", "/pulls", json={"title": title, "body": body, "head": head, "base": base}
            )
        if response.status_code == 422:
            raise RepoConflictError(
                "the provider rejected the pull request — it may already exist for this branch"
            )
        if response.status_code not in (200, 201):
            raise RepoError(f"could not open the pull request ({response.status_code})")

        data = response.json()
        return PullRequestResult(number=data["number"], url=data["html_url"], branch=head)


class GitBucketRepoClient(GitHubRepoClient):
    """GitBucket exposes GitHub's API shape under /api/v3 with `token` auth."""

    auth_scheme = "token"

    def __init__(self, token: str, repo_full_name: str, instance_url: str) -> None:
        super().__init__(token, repo_full_name)
        self.api_base = f"{instance_url.rstrip('/')}/api/v3"


class GitLabRepoClient:
    """Repository operations against GitLab.

    GitLab is not API-compatible with GitHub here, and the terminology
    differs in a way that reaches the UI: what GitHub calls a pull request,
    GitLab calls a merge request. The endpoint shapes differ too — notably,
    GitLab commits a multi-file change in a single call with a list of
    actions, so it needs no blob/tree assembly.
    """

    def __init__(self, token: str, repo_full_name: str, api_base: str = "https://gitlab.com/api/v4") -> None:
        self._token = token
        # GitLab addresses a project by its URL-encoded full path.
        self._project = quote(repo_full_name.strip("/"), safe="")
        self._api_base = api_base.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._api_base}/projects/{self._project}{path}"
        try:
            response = await client.request(method, url, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise RepoError(f"could not reach GitLab: {exc}") from exc

        if response.status_code in (401, 403):
            raise RepoAuthError("the stored GitLab token was rejected — reconnect the integration")
        if response.status_code == 404:
            raise RepoNotFoundError("project, branch, or file not found")
        if response.status_code >= 500:
            raise RepoError(f"GitLab returned {response.status_code}")
        return response

    async def get_file(self, path: str, ref: str) -> FileContent:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request(
                client, "GET", f"/repository/files/{quote(path, safe='')}", params={"ref": ref}
            )
        if response.status_code != 200:
            raise RepoError(f"could not read {path} ({response.status_code})")

        data = response.json()
        if data.get("size", 0) > MAX_FILE_BYTES:
            raise RepoTooLargeError(f"{path} exceeds the {MAX_FILE_BYTES // 1024}KB limit")

        return FileContent(
            path=path,
            content=_decode_blob(data.get("content", ""), data.get("encoding", "base64")),
            # blob_id is GitLab's equivalent of a git blob sha.
            sha=data.get("blob_id"),
            size=data.get("size", 0),
        )

    async def create_branch(self, base_branch: str, new_branch: str) -> str:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request(
                client, "POST", "/repository/branches", params={"branch": new_branch, "ref": base_branch}
            )
        if response.status_code == 400:
            raise RepoConflictError(f"branch {new_branch!r} already exists")
        if response.status_code not in (200, 201):
            raise RepoError(f"could not create branch {new_branch!r} ({response.status_code})")
        return response.json().get("commit", {}).get("id", "")

    async def _assert_no_conflicts(
        self, client: httpx.AsyncClient, changes: list[FileChange], ref: str
    ) -> None:
        for change in changes:
            response = await self._request(
                client,
                "GET",
                f"/repository/files/{quote(change.path, safe='')}",
                params={"ref": ref},
            )
            current = response.json().get("blob_id") if response.status_code == 200 else None

            if change.before_sha is None:
                if current is not None:
                    raise RepoConflictError(
                        f"{change.path} now exists on the remote — regenerate the change"
                    )
            elif current != change.before_sha:
                raise RepoConflictError(
                    f"{change.path} changed on the remote since this was prepared — "
                    "regenerate the change"
                )

    async def commit_files(
        self, branch: str, changes: list[FileChange], message: str, *, base_branch: str
    ) -> str:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await self._assert_no_conflicts(client, changes, base_branch)

            actions = [
                {
                    "action": "create" if change.before_sha is None else "update",
                    "file_path": change.path,
                    "content": change.content,
                }
                for change in changes
            ]
            response = await self._request(
                client,
                "POST",
                "/repository/commits",
                json={"branch": branch, "commit_message": message, "actions": actions},
            )
        if response.status_code not in (200, 201):
            raise RepoError(f"could not create the commit ({response.status_code})")
        return response.json().get("id", "")

    async def open_pull_request(
        self, *, title: str, body: str, head: str, base: str
    ) -> PullRequestResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await self._request(
                client,
                "POST",
                "/merge_requests",
                json={
                    "source_branch": head,
                    "target_branch": base,
                    "title": title,
                    "description": body,
                },
            )
        if response.status_code == 409:
            raise RepoConflictError("a merge request already exists for this branch")
        if response.status_code not in (200, 201):
            raise RepoError(f"could not open the merge request ({response.status_code})")

        data = response.json()
        return PullRequestResult(number=data["iid"], url=data["web_url"], branch=head)


RepoClient = GitHubRepoClient | GitBucketRepoClient | GitLabRepoClient


def build_repo_client(provider: str, token: str, repo_full_name: str) -> RepoClient:
    """Pick the right client for a provider, using configured instance URLs."""
    if provider == "github":
        return GitHubRepoClient(token, repo_full_name)
    if provider == "gitlab":
        return GitLabRepoClient(token, repo_full_name)
    if provider == "gitbucket":
        from graphify.server.config import get_settings

        settings = get_settings()
        instance_url = settings.gitbucket_instance_url
        if not instance_url:
            raise RepoError("GitBucket is not configured on this deployment")
        return GitBucketRepoClient(token, repo_full_name, instance_url)
    raise RepoError(f"unknown provider {provider!r}")


def provider_change_request_noun(provider: str) -> str:
    """GitLab calls it a merge request; the others call it a pull request."""
    return "merge request" if provider == "gitlab" else "pull request"
