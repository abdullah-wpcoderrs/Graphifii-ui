"""Tests for graphify/server/usage.py — estimate_cost only, no DB.

record_usage() itself needs a real AsyncSession and is covered by the
integration tests instead (test_launch_routes.py, test_admin_routes.py),
since its whole job is writing a row correctly — that's not meaningfully
testable without a database.
"""
from __future__ import annotations

from decimal import Decimal

from graphify.server.usage import estimate_cost


def test_anthropic_provider_name_maps_to_llm_py_claude_backend():
    """The admin UI calls this provider "anthropic"; llm.py's pricing table
    keys it "claude". Without the mapping in usage.py, every Anthropic call
    would silently price at $0 forever — this is the one regression that
    must never come back."""
    cost = estimate_cost("anthropic", "claude-sonnet-4-6", prompt_tokens=1000, completion_tokens=1000)
    assert cost > Decimal("0")


def test_unknown_provider_returns_zero_not_an_exception():
    cost = estimate_cost("some-provider-that-does-not-exist", "model-x", 1000, 1000)
    assert cost == Decimal("0")


def test_zero_tokens_costs_zero():
    cost = estimate_cost("openai", "gpt-4.1-mini", 0, 0)
    assert cost == Decimal("0")


def test_cost_scales_with_token_count():
    small = estimate_cost("openai", "gpt-4.1-mini", 1000, 1000)
    large = estimate_cost("openai", "gpt-4.1-mini", 10000, 10000)
    assert large > small


def test_cost_is_a_decimal_not_a_float():
    # Guards against Decimal(some_float) reintroducing float representation
    # error into a column that gets summed as money (see the module's
    # str()-first comment).
    cost = estimate_cost("openai", "gpt-4.1-mini", 123, 456)
    assert isinstance(cost, Decimal)
