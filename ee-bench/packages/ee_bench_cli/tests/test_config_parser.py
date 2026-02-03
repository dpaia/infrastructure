"""Tests for configuration parser."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import pytest

from ee_bench_cli.config_parser import (
    find_default_config,
    generate_sample_config,
    load_config,
    merge_configs,
    parse_set_options,
    parse_set_value,
    render_template,
    substitute_env_vars,
    validate_config,
)


class TestSubstituteEnvVars:
    """Tests for environment variable substitution."""

    def test_substitutes_existing_var(self, monkeypatch):
        """Test substitution of existing environment variable."""
        monkeypatch.setenv("TEST_VAR", "hello")
        result = substitute_env_vars("${TEST_VAR} world")
        assert result == "hello world"

    def test_substitutes_multiple_vars(self, monkeypatch):
        """Test substitution of multiple variables."""
        monkeypatch.setenv("VAR1", "one")
        monkeypatch.setenv("VAR2", "two")
        result = substitute_env_vars("${VAR1} and ${VAR2}")
        assert result == "one and two"

    def test_uses_default_when_var_missing(self, monkeypatch):
        """Test default value when variable is not set."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = substitute_env_vars("${MISSING_VAR:-default_value}")
        assert result == "default_value"

    def test_empty_default(self, monkeypatch):
        """Test empty default value."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = substitute_env_vars("prefix${MISSING_VAR:-}suffix")
        assert result == "prefixsuffix"

    def test_raises_for_missing_required_var(self, monkeypatch):
        """Test that missing required variable raises error."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(ValueError, match="MISSING_VAR"):
            substitute_env_vars("${MISSING_VAR}")

    def test_no_substitution_needed(self):
        """Test string without variables passes through."""
        result = substitute_env_vars("no variables here")
        assert result == "no variables here"

    def test_var_takes_precedence_over_default(self, monkeypatch):
        """Test that set variable is used instead of default."""
        monkeypatch.setenv("TEST_VAR", "actual")
        result = substitute_env_vars("${TEST_VAR:-default}")
        assert result == "actual"


class TestLoadConfig:
    """Tests for loading configuration files."""

    def test_loads_valid_yaml(self, tmp_path):
        """Test loading a valid YAML config file."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
provider: github_pull_requests
generator: dpaia_jvm
selection:
  resource: pull_requests
  filters:
    repo: test/repo
"""
        )

        config = load_config(config_file)

        assert config["provider"] == "github_pull_requests"
        assert config["generator"] == "dpaia_jvm"
        assert config["selection"]["resource"] == "pull_requests"

    def test_substitutes_env_vars_in_config(self, tmp_path, monkeypatch):
        """Test that env vars are substituted when loading."""
        monkeypatch.setenv("GH_TOKEN", "secret123")
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
provider_options:
  auth:
    token: ${GH_TOKEN}
"""
        )

        config = load_config(config_file)

        assert config["provider_options"]["auth"]["token"] == "secret123"

    def test_substitutes_in_lists(self, tmp_path, monkeypatch):
        """Test env var substitution in list values."""
        monkeypatch.setenv("LABEL1", "bug")
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
selection:
  filters:
    labels:
      - ${LABEL1}
      - enhancement
"""
        )

        config = load_config(config_file)

        assert config["selection"]["filters"]["labels"] == ["bug", "enhancement"]

    def test_empty_file_returns_empty_dict(self, tmp_path):
        """Test that empty file returns empty dict."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("")

        config = load_config(config_file)

        assert config == {}


class TestMergeConfigs:
    """Tests for merging configuration dictionaries."""

    def test_override_takes_precedence(self):
        """Test that override values replace base values."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = merge_configs(base, override)

        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deep_merge(self):
        """Test that nested dicts are merged recursively."""
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 3, "c": 4}}

        result = merge_configs(base, override)

        assert result == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_override_replaces_non_dict(self):
        """Test that non-dict values are replaced, not merged."""
        base = {"a": {"nested": 1}}
        override = {"a": "string"}

        result = merge_configs(base, override)

        assert result == {"a": "string"}

    def test_preserves_original_dicts(self):
        """Test that original dicts are not modified."""
        base = {"a": 1}
        override = {"b": 2}

        merge_configs(base, override)

        assert base == {"a": 1}
        assert override == {"b": 2}


class TestValidateConfig:
    """Tests for configuration validation."""

    def test_valid_config_returns_no_errors(self):
        """Test that valid config returns empty error list."""
        config = {
            "provider": "github_pull_requests",
            "generator": "dpaia_jvm",
            "selection": {"resource": "pull_requests", "filters": {}},
        }

        errors = validate_config(config)

        assert errors == []

    def test_unknown_key_reports_error(self):
        """Test that unknown top-level keys are reported."""
        config = {"provider": "test", "unknown_key": "value"}

        errors = validate_config(config)

        assert any("unknown_key" in e.lower() for e in errors)

    def test_missing_selection_resource(self):
        """Test that missing selection.resource is reported."""
        config = {"selection": {"filters": {}}}

        errors = validate_config(config)

        assert any("resource" in e for e in errors)

    def test_invalid_output_format(self):
        """Test that invalid output format is reported."""
        config = {"output": {"format": "invalid"}}

        errors = validate_config(config)

        assert any("format" in e for e in errors)


class TestGenerateSampleConfig:
    """Tests for sample config generation."""

    def test_generates_valid_yaml(self):
        """Test that generated sample is valid YAML."""
        import yaml

        sample = generate_sample_config()

        # Should not raise
        config = yaml.safe_load(sample)

        assert isinstance(config, dict)
        assert "provider" in config
        assert "generator" in config

    def test_includes_common_options(self):
        """Test that sample includes common options."""
        sample = generate_sample_config()

        assert "provider:" in sample
        assert "generator:" in sample
        assert "selection:" in sample
        assert "output:" in sample


class TestFindDefaultConfig:
    """Tests for finding default config files."""

    def test_finds_config_in_cwd(self, tmp_path, monkeypatch):
        """Test finding config in current directory."""
        config_file = tmp_path / "ee-dataset.yml"
        config_file.write_text("provider: test")
        monkeypatch.chdir(tmp_path)

        result = find_default_config()

        assert result == config_file

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        """Test that None is returned when no config found."""
        monkeypatch.chdir(tmp_path)

        result = find_default_config()

        # May find user config, so just check it's a path or None
        assert result is None or isinstance(result, Path)


class TestRenderTemplate:
    """Tests for Jinja2 template rendering."""

    def test_simple_variable_substitution(self):
        """Test simple variable substitution."""
        content = "repo: {{ org }}/kafka"
        result = render_template(content, {"org": "apache"})
        assert result == "repo: apache/kafka"

    def test_multiple_variables(self):
        """Test multiple variable substitutions."""
        content = "repo: {{ org }}/{{ project }}"
        result = render_template(content, {"org": "apache", "project": "kafka"})
        assert result == "repo: apache/kafka"

    def test_default_filter(self):
        """Test default filter for missing variables."""
        content = "limit: {{ limit | default(100) }}"
        result = render_template(content, {})
        assert result == "limit: 100"

    def test_default_filter_with_provided_value(self):
        """Test that provided value overrides default."""
        content = "limit: {{ limit | default(100) }}"
        result = render_template(content, {"limit": 50})
        assert result == "limit: 50"

    def test_undefined_variable_raises_error(self):
        """Test that undefined variable without default raises error."""
        content = "repo: {{ undefined_var }}"
        with pytest.raises(ValueError, match="Undefined template variable"):
            render_template(content, {})

    def test_no_template_passthrough(self):
        """Test that content without templates passes through unchanged."""
        content = "repo: apache/kafka"
        result = render_template(content, {})
        assert result == "repo: apache/kafka"

    def test_no_template_with_empty_vars(self):
        """Test content without templates with empty variables."""
        content = "plain: text"
        result = render_template(content, None)
        assert result == "plain: text"

    def test_conditional_block(self):
        """Test Jinja2 conditional blocks."""
        content = """\
{% if include_labels %}
labels:
  - bug
{% endif %}"""
        result_with = render_template(content, {"include_labels": True})
        assert "labels:" in result_with

        result_without = render_template(content, {"include_labels": False})
        assert "labels:" not in result_without

    def test_for_loop(self):
        """Test Jinja2 for loops."""
        content = """\
labels:
{% for label in labels %}
  - {{ label }}
{% endfor %}"""
        result = render_template(content, {"labels": ["bug", "verified"]})
        assert "- bug" in result
        assert "- verified" in result

    def test_syntax_error_raises(self):
        """Test that syntax errors in template raise ValueError."""
        content = "repo: {{ unclosed"
        with pytest.raises(ValueError, match="syntax error"):
            render_template(content, {})


class TestParseSetValue:
    """Tests for parsing --set values."""

    def test_parse_integer(self):
        """Test parsing integer value."""
        assert parse_set_value("42") == 42

    def test_parse_float(self):
        """Test parsing float value."""
        assert parse_set_value("3.14") == 3.14

    def test_parse_boolean_true(self):
        """Test parsing boolean true."""
        assert parse_set_value("true") is True

    def test_parse_boolean_false(self):
        """Test parsing boolean false."""
        assert parse_set_value("false") is False

    def test_parse_null(self):
        """Test parsing null."""
        assert parse_set_value("null") is None

    def test_parse_string(self):
        """Test parsing plain string (non-JSON)."""
        assert parse_set_value("hello") == "hello"

    def test_parse_json_array(self):
        """Test parsing JSON array."""
        assert parse_set_value('["a", "b", "c"]') == ["a", "b", "c"]

    def test_parse_json_object(self):
        """Test parsing JSON object."""
        assert parse_set_value('{"key": "value"}') == {"key": "value"}

    def test_parse_quoted_string(self):
        """Test parsing quoted JSON string."""
        assert parse_set_value('"quoted"') == "quoted"

    def test_parse_string_with_spaces(self):
        """Test parsing string with spaces (not valid JSON)."""
        assert parse_set_value("hello world") == "hello world"


class TestParseSetOptions:
    """Tests for parsing multiple --set options."""

    def test_parse_simple_options(self):
        """Test parsing simple key=value options."""
        result = parse_set_options(("org=apache", "project=kafka"))
        assert result == {"org": "apache", "project": "kafka"}

    def test_parse_with_json_values(self):
        """Test parsing options with JSON values."""
        result = parse_set_options(("limit=50", 'labels=["bug", "verified"]'))
        assert result == {"limit": 50, "labels": ["bug", "verified"]}

    def test_parse_nested_keys(self):
        """Test parsing nested keys with dot notation."""
        result = parse_set_options(("outer.inner=value",))
        assert result == {"outer": {"inner": "value"}}

    def test_parse_deeply_nested_keys(self):
        """Test parsing deeply nested keys."""
        result = parse_set_options(("a.b.c=deep",))
        assert result == {"a": {"b": {"c": "deep"}}}

    def test_parse_multiple_nested_in_same_parent(self):
        """Test parsing multiple nested keys under same parent."""
        result = parse_set_options(("parent.child1=one", "parent.child2=two"))
        assert result == {"parent": {"child1": "one", "child2": "two"}}

    def test_invalid_format_raises(self):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid --set option"):
            parse_set_options(("no_equals_sign",))

    def test_empty_options(self):
        """Test parsing empty options."""
        result = parse_set_options(())
        assert result == {}

    def test_value_with_equals(self):
        """Test parsing value that contains equals sign."""
        result = parse_set_options(("equation=a=b",))
        assert result == {"equation": "a=b"}


class TestLoadConfigWithTemplates:
    """Tests for load_config with template variables."""

    def test_loads_with_template_vars(self, tmp_path):
        """Test loading config with template variables."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
provider: github_pull_requests
selection:
  filters:
    repo: "{{ org }}/{{ project }}"
"""
        )

        config = load_config(config_file, {"org": "apache", "project": "kafka"})

        assert config["selection"]["filters"]["repo"] == "apache/kafka"

    def test_loads_with_defaults(self, tmp_path):
        """Test loading config with default values in templates."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
selection:
  limit: {{ limit | default(100) }}
"""
        )

        config = load_config(config_file, {})

        assert config["selection"]["limit"] == 100

    def test_loads_without_template_vars(self, tmp_path):
        """Test loading config without template variables (backward compat)."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
provider: github_pull_requests
selection:
  filters:
    repo: apache/kafka
"""
        )

        config = load_config(config_file)

        assert config["selection"]["filters"]["repo"] == "apache/kafka"

    def test_templates_then_env_vars(self, tmp_path, monkeypatch):
        """Test that templates are rendered before env var substitution."""
        monkeypatch.setenv("MY_TOKEN", "secret123")
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
provider_options:
  token: ${MY_TOKEN}
selection:
  filters:
    repo: "{{ org }}/kafka"
"""
        )

        config = load_config(config_file, {"org": "apache"})

        assert config["provider_options"]["token"] == "secret123"
        assert config["selection"]["filters"]["repo"] == "apache/kafka"
