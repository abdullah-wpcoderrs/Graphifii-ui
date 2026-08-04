"""Unit tests for the provider REST clients in repo_api.py.

No network, no live GitHub/GitLab/GitBucket calls: httpx.AsyncClient.request
is monkeypatched at the class level with a fake dispatcher per test, keyed
on (method, url). This exercises the real request-building and
response-parsing logic in each client without a real socket.
"""

from __future__ import annotations

import json as jsonlib
from unittest.mock import AsyncMock

import httpx
import pytest

from graphify.server.repo_api import (
    FileChange,
    GitBucketRepoClient,
    GitHubRepoClient,
    GitLabRepoClient,
    RepoAuthError,
    RepoConflictError,
    RepoError,
    RepoNotFoundError,
    RepoTooLargeError,
    build_repo_client,
    provider_change_request_noun,
)


def _resp(status_code: int, json_body: dict | list | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://example.test/")
    content = jsonlib.dumps(json_body).encode() if json_body is not None else b""
    return httpx.Response(status_code, content=content, request=request)


def _install_dispatcher(monkeypatch, handler):
    """handler(method, url, kwargs) -> httpx.Response"""

    async def fake_request(self, method, url, **kwargs):
        return handler(method, url, kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)


# --- GitHubRepoClient.get_file -----------------------------------------------


async def test_github_get_file_decodes_base64_content(monkeypatch):
    import base64

    def handler(method, url, kwargs):
        assert method == "GET"
        assert url == "https://api.github.com/repos/o/r/contents/src/main.py"
        assert kwargs["params"] == {"ref": "main"}
        return _resp(
            200,
            {
                "content": base64.b64encode(b"print('hi')").decode(),
                "encoding": "base64",
                "sha": "abc123",
                "size": 11,
            },
        )

    _install_dispatcher(monkeypatch, handler)
    client = GitHubRepoClient("tok", "o/r")
    result = await client.get_file("src/main.py", "main")
    assert result.content == "print('hi')"
    assert result.sha == "abc123"


async def test_github_get_file_rejects_directory(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(200, [{"name": "a"}]))
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoError, match="directory"):
        await client.get_file("src", "main")


async def test_github_get_file_too_large(monkeypatch):
    _install_dispatcher(
        monkeypatch,
        lambda m, u, k: _resp(200, {"content": "", "encoding": "base64", "sha": "x", "size": 10_000_000}),
    )
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoTooLargeError):
        await client.get_file("big.bin", "main")


async def test_github_get_file_not_found(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(404))
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoNotFoundError):
        await client.get_file("missing.py", "main")


async def test_github_get_file_auth_rejected(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(401))
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoAuthError):
        await client.get_file("f.py", "main")


async def test_github_request_network_error_wrapped(monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoError, match="could not reach"):
        await client.get_file("f.py", "main")


async def test_github_5xx_wrapped_as_repo_error(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(503))
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoError, match="503"):
        await client.get_file("f.py", "main")


# --- GitHubRepoClient.create_branch ------------------------------------------


async def test_github_create_branch_happy_path(monkeypatch):
    calls = []

    def handler(method, url, kwargs):
        calls.append((method, url))
        if url.endswith("/git/ref/heads/main"):
            return _resp(200, {"object": {"sha": "base-sha"}})
        if url.endswith("/git/refs"):
            assert kwargs["json"] == {"ref": "refs/heads/feature", "sha": "base-sha"}
            return _resp(201, {})
        raise AssertionError(f"unexpected call {method} {url}")

    _install_dispatcher(monkeypatch, handler)
    client = GitHubRepoClient("tok", "o/r")
    base_sha = await client.create_branch("main", "feature")
    assert base_sha == "base-sha"
    assert len(calls) == 2


async def test_github_create_branch_already_exists(monkeypatch):
    def handler(method, url, kwargs):
        if "git/ref/heads" in url:
            return _resp(200, {"object": {"sha": "base-sha"}})
        return _resp(422, {"message": "Reference already exists"})

    _install_dispatcher(monkeypatch, handler)
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoConflictError, match="already exists"):
        await client.create_branch("main", "feature")


async def test_github_create_branch_base_not_found(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(404))
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoNotFoundError):
        await client.create_branch("nonexistent", "feature")


# --- GitHubRepoClient.commit_files -------------------------------------------


def _github_commit_handler(*, conflict=False, ref_move_fails=False):
    def handler(method, url, kwargs):
        if "contents/" in url and method == "GET":
            # _assert_no_conflicts: current file sha lookup
            if conflict:
                return _resp(200, {"sha": "moved-sha"})
            return _resp(200, {"sha": "orig-sha"})
        if url.endswith("/git/ref/heads/feature"):
            return _resp(200, {"object": {"sha": "parent-sha"}})
        if "/git/commits/parent-sha" in url:
            return _resp(200, {"tree": {"sha": "base-tree-sha"}})
        if url.endswith("/git/blobs"):
            return _resp(201, {"sha": "blob-sha"})
        if url.endswith("/git/trees"):
            return _resp(201, {"sha": "new-tree-sha"})
        if url.endswith("/git/commits"):
            return _resp(201, {"sha": "new-commit-sha"})
        if url.endswith("/git/refs/heads/feature") and method == "PATCH":
            if ref_move_fails:
                return _resp(422, {})
            return _resp(200, {})
        raise AssertionError(f"unexpected call {method} {url}")

    return handler


async def test_github_commit_files_happy_path(monkeypatch):
    _install_dispatcher(monkeypatch, _github_commit_handler())
    client = GitHubRepoClient("tok", "o/r")
    changes = [FileChange(path="a.py", content="x = 1", before_sha="orig-sha")]
    commit_sha = await client.commit_files("feature", changes, "msg", base_branch="main")
    assert commit_sha == "new-commit-sha"


async def test_github_commit_files_conflict_on_moved_file(monkeypatch):
    _install_dispatcher(monkeypatch, _github_commit_handler(conflict=True))
    client = GitHubRepoClient("tok", "o/r")
    changes = [FileChange(path="a.py", content="x = 1", before_sha="orig-sha")]
    with pytest.raises(RepoConflictError, match="changed on the remote"):
        await client.commit_files("feature", changes, "msg", base_branch="main")


async def test_github_commit_files_conflict_when_creating_existing_file(monkeypatch):
    def handler(method, url, kwargs):
        if "contents/" in url and method == "GET":
            return _resp(200, {"sha": "surprise-sha"})
        raise AssertionError("should not reach past the conflict check")

    _install_dispatcher(monkeypatch, handler)
    client = GitHubRepoClient("tok", "o/r")
    changes = [FileChange(path="new.py", content="x = 1", before_sha=None)]
    with pytest.raises(RepoConflictError, match="now exists on the remote"):
        await client.commit_files("feature", changes, "msg", base_branch="main")


async def test_github_commit_files_ref_move_failure(monkeypatch):
    _install_dispatcher(monkeypatch, _github_commit_handler(ref_move_fails=True))
    client = GitHubRepoClient("tok", "o/r")
    changes = [FileChange(path="a.py", content="x = 1", before_sha="orig-sha")]
    with pytest.raises(RepoError, match="could not move branch"):
        await client.commit_files("feature", changes, "msg", base_branch="main")


# --- GitHubRepoClient.open_pull_request --------------------------------------


async def test_github_open_pull_request_happy_path(monkeypatch):
    def handler(method, url, kwargs):
        assert url.endswith("/pulls")
        assert kwargs["json"] == {
            "title": "My PR",
            "body": "desc",
            "head": "feature",
            "base": "main",
        }
        return _resp(201, {"number": 42, "html_url": "https://github.com/o/r/pull/42"})

    _install_dispatcher(monkeypatch, handler)
    client = GitHubRepoClient("tok", "o/r")
    result = await client.open_pull_request(title="My PR", body="desc", head="feature", base="main")
    assert result.number == 42
    assert result.url == "https://github.com/o/r/pull/42"
    assert result.branch == "feature"


async def test_github_open_pull_request_conflict(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(422, {}))
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoConflictError, match="may already exist"):
        await client.open_pull_request(title="t", body="b", head="feature", base="main")


async def test_github_open_pull_request_generic_error(monkeypatch):
    # A status _request() doesn't special-case (not 401/403/404/409/5xx) so
    # it falls through to open_pull_request's own "not 200/201" handling.
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(400, {}))
    client = GitHubRepoClient("tok", "o/r")
    with pytest.raises(RepoError, match="could not open"):
        await client.open_pull_request(title="t", body="b", head="feature", base="main")


# --- GitBucketRepoClient ------------------------------------------------------


async def test_gitbucket_uses_api_v3_base_and_token_scheme(monkeypatch):
    client = GitBucketRepoClient("tok", "o/r", "https://git.internal")
    assert client.api_base == "https://git.internal/api/v3"
    assert client.auth_scheme == "token"
    assert client._headers["Authorization"] == "token tok"


async def test_gitbucket_open_pull_request_hits_instance_url(monkeypatch):
    def handler(method, url, kwargs):
        assert url == "https://git.internal/api/v3/repos/o/r/pulls"
        return _resp(201, {"number": 7, "html_url": "https://git.internal/o/r/pull/7"})

    _install_dispatcher(monkeypatch, handler)
    client = GitBucketRepoClient("tok", "o/r", "https://git.internal")
    result = await client.open_pull_request(title="t", body="b", head="feature", base="main")
    assert result.number == 7


# --- GitLabRepoClient ---------------------------------------------------------


async def test_gitlab_get_file_uses_blob_id_as_sha(monkeypatch):
    import base64

    def handler(method, url, kwargs):
        assert url == "https://gitlab.com/api/v4/projects/o%2Fr/repository/files/src%2Fmain.py"
        return _resp(
            200,
            {
                "content": base64.b64encode(b"print(1)").decode(),
                "encoding": "base64",
                "blob_id": "gl-blob-1",
                "size": 8,
            },
        )

    _install_dispatcher(monkeypatch, handler)
    client = GitLabRepoClient("tok", "o/r")
    result = await client.get_file("src/main.py", "main")
    assert result.sha == "gl-blob-1"
    assert result.content == "print(1)"


async def test_gitlab_create_branch_already_exists(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(400, {"message": "already exists"}))
    client = GitLabRepoClient("tok", "o/r")
    with pytest.raises(RepoConflictError):
        await client.create_branch("main", "feature")


async def test_gitlab_commit_files_uses_actions_api(monkeypatch):
    def handler(method, url, kwargs):
        if "repository/files/" in url and method == "GET":
            return _resp(200, {"blob_id": "orig-blob"})
        if url.endswith("/repository/commits"):
            assert kwargs["json"]["actions"] == [
                {"action": "update", "file_path": "a.py", "content": "x = 1"}
            ]
            return _resp(201, {"id": "gl-commit-1"})
        raise AssertionError(f"unexpected call {method} {url}")

    _install_dispatcher(monkeypatch, handler)
    client = GitLabRepoClient("tok", "o/r")
    changes = [FileChange(path="a.py", content="x = 1", before_sha="orig-blob")]
    commit_id = await client.commit_files("feature", changes, "msg", base_branch="main")
    assert commit_id == "gl-commit-1"


async def test_gitlab_commit_files_conflict_on_moved_file(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(200, {"blob_id": "moved-blob"}))
    client = GitLabRepoClient("tok", "o/r")
    changes = [FileChange(path="a.py", content="x = 1", before_sha="orig-blob")]
    with pytest.raises(RepoConflictError, match="changed on the remote"):
        await client.commit_files("feature", changes, "msg", base_branch="main")


async def test_gitlab_open_merge_request_happy_path(monkeypatch):
    def handler(method, url, kwargs):
        assert url.endswith("/merge_requests")
        assert kwargs["json"] == {
            "source_branch": "feature",
            "target_branch": "main",
            "title": "t",
            "description": "b",
        }
        return _resp(201, {"iid": 5, "web_url": "https://gitlab.com/o/r/-/merge_requests/5"})

    _install_dispatcher(monkeypatch, handler)
    client = GitLabRepoClient("tok", "o/r")
    result = await client.open_pull_request(title="t", body="b", head="feature", base="main")
    assert result.number == 5
    assert result.url == "https://gitlab.com/o/r/-/merge_requests/5"


async def test_gitlab_open_merge_request_conflict(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(409, {}))
    client = GitLabRepoClient("tok", "o/r")
    with pytest.raises(RepoConflictError, match="already exists"):
        await client.open_pull_request(title="t", body="b", head="feature", base="main")


async def test_gitlab_auth_rejected(monkeypatch):
    _install_dispatcher(monkeypatch, lambda m, u, k: _resp(403))
    client = GitLabRepoClient("tok", "o/r")
    with pytest.raises(RepoAuthError):
        await client.get_file("f.py", "main")


# --- build_repo_client / provider_change_request_noun -------------------------


def test_build_repo_client_dispatches_by_provider(monkeypatch):
    assert isinstance(build_repo_client("github", "t", "o/r"), GitHubRepoClient)
    assert isinstance(build_repo_client("gitlab", "t", "o/r"), GitLabRepoClient)

    from graphify.server.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("GITBUCKET_INSTANCE_URL", "https://git.internal")
    get_settings.cache_clear()
    try:
        assert isinstance(build_repo_client("gitbucket", "t", "o/r"), GitBucketRepoClient)
    finally:
        get_settings.cache_clear()


def test_build_repo_client_unknown_provider():
    with pytest.raises(RepoError, match="unknown provider"):
        build_repo_client("bitbucket", "t", "o/r")


def test_build_repo_client_gitbucket_requires_instance_url(monkeypatch):
    from graphify.server.config import get_settings

    monkeypatch.delenv("GITBUCKET_INSTANCE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RepoError, match="not configured"):
            build_repo_client("gitbucket", "t", "o/r")
    finally:
        get_settings.cache_clear()


def test_provider_change_request_noun():
    assert provider_change_request_noun("gitlab") == "merge request"
    assert provider_change_request_noun("github") == "pull request"
    assert provider_change_request_noun("gitbucket") == "pull request"
