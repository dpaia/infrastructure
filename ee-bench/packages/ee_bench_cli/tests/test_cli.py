"""Tests for CLI commands."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from ee_bench_cli.cli import cli


@pytest.fixture
def runner():
    """Create a CLI test runner."""
    return CliRunner()


class TestCli:
    """Tests for main CLI."""

    def test_help(self, runner):
        """Test --help shows usage."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "ee-dataset" in result.output
        assert "generate" in result.output
        assert "list" in result.output

    def test_version(self, runner):
        """Test --version shows version."""
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestListCommand:
    """Tests for list command."""

    def test_list_shows_no_plugins(self, runner):
        """Test list with no plugins installed."""
        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        # Should show "No providers" and "No generators" messages
        assert "No providers" in result.output or "Providers:" in result.output

    def test_list_providers_only(self, runner):
        """Test list with --providers flag."""
        result = runner.invoke(cli, ["list", "--providers"])

        assert result.exit_code == 0

    def test_list_generators_only(self, runner):
        """Test list with --generators flag."""
        result = runner.invoke(cli, ["list", "--generators"])

        assert result.exit_code == 0


class TestConfigCommands:
    """Tests for config subcommands."""

    def test_config_init(self, runner):
        """Test config init generates sample."""
        result = runner.invoke(cli, ["config", "init"])

        assert result.exit_code == 0
        assert "provider:" in result.output
        assert "generator:" in result.output
        assert "selection:" in result.output

    def test_config_validate_valid(self, runner, tmp_path):
        """Test config validate with valid config."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
provider: github_pull_requests
generator: dpaia_jvm
selection:
  resource: pull_requests
"""
        )

        result = runner.invoke(cli, ["config", "validate", str(config_file)])

        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_config_validate_invalid_yaml(self, runner, tmp_path):
        """Test config validate with invalid YAML."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("invalid: yaml: syntax:")

        result = runner.invoke(cli, ["config", "validate", str(config_file)])

        assert result.exit_code == 1

    def test_config_show_no_config(self, runner, tmp_path, monkeypatch):
        """Test config show when no config exists."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["config", "show"])

        assert result.exit_code == 0
        assert "No configuration file found" in result.output

    def test_config_show_with_file(self, runner, tmp_path):
        """Test config show with explicit file."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("provider: test_provider")

        result = runner.invoke(cli, ["config", "show", "--path", str(config_file)])

        assert result.exit_code == 0
        assert "test_provider" in result.output


class TestShowCommand:
    """Tests for show command."""

    def test_show_nonexistent_provider(self, runner):
        """Test show with nonexistent provider."""
        result = runner.invoke(cli, ["show", "provider", "nonexistent"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_show_nonexistent_generator(self, runner):
        """Test show with nonexistent generator."""
        result = runner.invoke(cli, ["show", "generator", "nonexistent"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestCheckCommand:
    """Tests for check command."""

    def test_check_nonexistent_provider(self, runner):
        """Test check with nonexistent provider."""
        result = runner.invoke(
            cli, ["check", "--provider", "nonexistent", "--generator", "test"]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_check_nonexistent_generator(self, runner):
        """Test check with nonexistent generator."""
        result = runner.invoke(
            cli, ["check", "--provider", "test", "--generator", "nonexistent"]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestGenerateCommand:
    """Tests for generate command."""

    def test_generate_nonexistent_provider(self, runner):
        """Test generate with nonexistent provider."""
        result = runner.invoke(
            cli,
            [
                "generate",
                "--provider",
                "nonexistent",
                "--generator",
                "test",
                "--selection",
                '{"resource": "test"}',
            ],
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_generate_invalid_selection_json(self, runner):
        """Test generate with invalid selection JSON."""
        result = runner.invoke(
            cli,
            [
                "generate",
                "--provider",
                "test",
                "--generator",
                "test",
                "--selection",
                "not valid json",
            ],
        )

        assert result.exit_code != 0


class TestSchemaCommand:
    """Tests for schema command."""

    def test_schema_nonexistent_generator(self, runner):
        """Test schema with nonexistent generator."""
        result = runner.invoke(cli, ["schema", "--generator", "nonexistent"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestValidateCommand:
    """Tests for validate command."""

    def test_validate_nonexistent_generator(self, runner, tmp_path):
        """Test validate with nonexistent generator."""
        data_file = tmp_path / "data.jsonl"
        data_file.write_text('{"test": "data"}\n')

        result = runner.invoke(
            cli, ["validate", str(data_file), "--generator", "nonexistent"]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestSetOption:
    """Tests for --set / -S option."""

    def test_set_option_in_help(self, runner):
        """Test that --set option appears in help."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "--set" in result.output or "-S" in result.output

    def test_set_simple_value(self, runner, tmp_path):
        """Test --set with simple value."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
provider: github_pull_requests
selection:
  resource: pull_requests
  filters:
    repo: "{{ org }}/kafka"
"""
        )

        result = runner.invoke(
            cli,
            ["-c", str(config_file), "-S", "org=apache", "config", "show"],
        )

        assert result.exit_code == 0
        assert "apache/kafka" in result.output

    def test_set_multiple_values(self, runner, tmp_path):
        """Test multiple -S options."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
selection:
  filters:
    repo: "{{ org }}/{{ project }}"
"""
        )

        result = runner.invoke(
            cli,
            [
                "-c",
                str(config_file),
                "-S",
                "org=apache",
                "-S",
                "project=kafka",
                "config",
                "show",
            ],
        )

        assert result.exit_code == 0
        assert "apache/kafka" in result.output

    def test_set_json_value(self, runner, tmp_path):
        """Test --set with JSON array value."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
selection:
  filters:
    labels: {{ labels }}
"""
        )

        result = runner.invoke(
            cli,
            ["-c", str(config_file), "-S", 'labels=["bug", "verified"]', "config", "show"],
        )

        assert result.exit_code == 0
        assert "bug" in result.output
        assert "verified" in result.output

    def test_set_with_default(self, runner, tmp_path):
        """Test template with default value when --set provides other vars."""
        config_file = tmp_path / "config.yml"
        config_file.write_text(
            """
selection:
  limit: {{ limit | default(100) }}
"""
        )

        # Jinja2 rendering only triggers when --set is used;
        # pass an unrelated var so that the template default kicks in.
        result = runner.invoke(
            cli,
            ["-c", str(config_file), "-S", "unused=1", "config", "show"],
        )

        assert result.exit_code == 0
        assert "100" in result.output

    def test_set_invalid_format(self, runner, tmp_path):
        """Test --set with invalid format raises error."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("provider: test")

        result = runner.invoke(
            cli,
            ["-c", str(config_file), "-S", "invalid_no_equals", "config", "show"],
        )

        assert result.exit_code != 0
        assert "Invalid" in result.output
