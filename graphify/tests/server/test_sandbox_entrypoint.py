"""Tests for scripts/sandbox_entrypoint.py — the code that runs inside the
Railway container. No DB, no network, no Docker: pure function tests only.

Imported by file path (importlib) rather than as a package, since
scripts/sandbox_entrypoint.py is a standalone script run via `python
sandbox_entrypoint.py` inside the container image, not part of the
installed graphify package.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "sandbox_entrypoint.py"


@pytest.fixture()
def sbx(monkeypatch):
    spec = importlib.util.spec_from_file_location("sandbox_entrypoint_under_test", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- authenticated_clone_url -------------------------------------------------


def test_clone_url_injects_token_for_https(sbx):
    url = sbx.authenticated_clone_url("https://github.com/o/r.git", "ghp_secret123")
    assert url == "https://x-access-token:ghp_secret123@github.com/o/r.git"


def test_clone_url_unchanged_for_public_repo(sbx):
    url = sbx.authenticated_clone_url("https://github.com/o/r.git", None)
    assert url == "https://github.com/o/r.git"


def test_clone_url_unchanged_for_ssh_urls(sbx):
    """SSH URLs don't take HTTP basic auth — injecting a token there would
    just be silently ignored by git at best, or malform the URL at worst."""
    url = sbx.authenticated_clone_url("git@github.com:o/r.git", "ghp_secret123")
    assert url == "git@github.com:o/r.git"


def test_clone_url_never_contains_token_in_plaintext_form_twice(sbx):
    # Sanity check the token appears exactly where expected and nowhere else
    # (e.g. not duplicated into a query string by a careless urlsplit/urlunsplit bug).
    url = sbx.authenticated_clone_url("https://github.com/o/r.git", "SECRETVALUE")
    assert url.count("SECRETVALUE") == 1


# --- detect_llm_backend -------------------------------------------------


@pytest.mark.parametrize(
    "env_var,expected_backend",
    [("ANTHROPIC_API_KEY", "claude"), ("OPENAI_API_KEY", "openai"), ("GEMINI_API_KEY", "gemini")],
)
def test_detect_llm_backend_maps_env_var_to_backend_name(sbx, monkeypatch, env_var, expected_backend):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(env_var, "some-key-value")
    assert sbx.detect_llm_backend() == expected_backend


def test_detect_llm_backend_returns_none_when_no_key_present(sbx, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert sbx.detect_llm_backend() is None


def test_detect_llm_backend_prefers_anthropic_when_multiple_keys_present(sbx, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "b")
    assert sbx.detect_llm_backend() == "claude"


# --- parse_token_cost -------------------------------------------------


def test_parse_token_cost_extracts_comma_formatted_numbers(sbx, tmp_path):
    report = tmp_path / "GRAPH_REPORT.md"
    report.write_text("- Token cost: 12,345 input · 6,789 output\n")
    assert sbx.parse_token_cost(report) == (12345, 6789)


def test_parse_token_cost_handles_zero(sbx, tmp_path):
    report = tmp_path / "GRAPH_REPORT.md"
    report.write_text("- Token cost: 0 input · 0 output\n")
    assert sbx.parse_token_cost(report) == (0, 0)


def test_parse_token_cost_returns_none_when_file_missing(sbx, tmp_path):
    assert sbx.parse_token_cost(tmp_path / "does-not-exist.md") is None


def test_parse_token_cost_returns_none_when_line_absent(sbx, tmp_path):
    """No LLM key present -> labeling never ran -> no Token cost line at
    all. Must not raise or false-positive as (0, 0)."""
    report = tmp_path / "GRAPH_REPORT.md"
    report.write_text("# Some report\n- Nodes: 17\n")
    assert sbx.parse_token_cost(report) is None


# --- build_files_json -------------------------------------------------


def test_build_files_json_lists_real_files_and_skips_junk_dirs(sbx, monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("// junk")

    monkeypatch.setattr(sbx, "WORKSPACE", tmp_path)
    result = sbx.build_files_json()

    paths = {f["path"] for f in result["files"]}
    assert "src/main.py" in paths
    assert not any(".git" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert result["truncated"] is False


def test_build_files_json_reports_truncation_past_the_cap(sbx, monkeypatch, tmp_path):
    for i in range(5):
        (tmp_path / f"file_{i}.txt").write_text("x")

    monkeypatch.setattr(sbx, "WORKSPACE", tmp_path)
    monkeypatch.setattr(sbx, "MAX_TREE_ENTRIES", 3)
    result = sbx.build_files_json()

    assert result["count"] == 3
    assert result["truncated"] is True


def test_build_files_json_is_json_serializable(sbx, monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x")
    monkeypatch.setattr(sbx, "WORKSPACE", tmp_path)
    json.dumps(sbx.build_files_json())  # must not raise
