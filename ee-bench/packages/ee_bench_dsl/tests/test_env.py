"""Tests for ee_bench_dsl.env."""

from __future__ import annotations

import os

import pytest

from ee_bench_dsl.env import env


class TestEnv:
    def test_reads_existing_var(self, monkeypatch):
        monkeypatch.setenv("TEST_DSL_VAR", "hello")
        assert env("TEST_DSL_VAR") == "hello"

    def test_raises_on_missing_required(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_DSL_VAR", raising=False)
        with pytest.raises(ValueError, match="Required environment variable"):
            env("NONEXISTENT_DSL_VAR")

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_DSL_VAR", raising=False)
        assert env("NONEXISTENT_DSL_VAR", "fallback") == "fallback"

    def test_returns_empty_string_default(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_DSL_VAR", raising=False)
        assert env("NONEXISTENT_DSL_VAR", "") == ""

    def test_env_var_takes_precedence_over_default(self, monkeypatch):
        monkeypatch.setenv("TEST_DSL_VAR", "real")
        assert env("TEST_DSL_VAR", "fallback") == "real"
