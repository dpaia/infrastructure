"""Tests for output serialization."""

import json
from pathlib import Path

import pytest
import yaml

from ee_bench_cli.output import format_record, write_records


class TestWriteRecords:
    """Tests for write_records function."""

    def test_write_jsonl(self, tmp_path):
        """Test writing records as JSON Lines."""
        output_path = tmp_path / "output.jsonl"
        records = iter([{"id": 1, "name": "first"}, {"id": 2, "name": "second"}])

        count = write_records(records, output_path, "jsonl")

        assert count == 2
        assert output_path.exists()

        lines = output_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"id": 1, "name": "first"}
        assert json.loads(lines[1]) == {"id": 2, "name": "second"}

    def test_write_json(self, tmp_path):
        """Test writing records as JSON array."""
        output_path = tmp_path / "output.json"
        records = iter([{"id": 1}, {"id": 2}])

        count = write_records(records, output_path, "json")

        assert count == 2
        assert output_path.exists()

        data = json.loads(output_path.read_text())
        assert data == [{"id": 1}, {"id": 2}]

    def test_write_yaml(self, tmp_path):
        """Test writing records as YAML."""
        output_path = tmp_path / "output.yaml"
        records = iter([{"id": 1, "name": "test"}])

        count = write_records(records, output_path, "yaml")

        assert count == 1
        assert output_path.exists()

        data = yaml.safe_load(output_path.read_text())
        assert data == [{"id": 1, "name": "test"}]

    def test_creates_parent_directories(self, tmp_path):
        """Test that parent directories are created."""
        output_path = tmp_path / "nested" / "dir" / "output.jsonl"
        records = iter([{"id": 1}])

        write_records(records, output_path, "jsonl")

        assert output_path.exists()

    def test_empty_records(self, tmp_path):
        """Test writing empty records."""
        output_path = tmp_path / "output.jsonl"
        records = iter([])

        count = write_records(records, output_path, "jsonl")

        assert count == 0
        assert output_path.exists()
        assert output_path.read_text() == ""

    def test_invalid_format_raises(self, tmp_path):
        """Test that invalid format raises ValueError."""
        output_path = tmp_path / "output.txt"
        records = iter([{"id": 1}])

        with pytest.raises(ValueError, match="Unknown output format"):
            write_records(records, output_path, "invalid")

    def test_unicode_content(self, tmp_path):
        """Test that unicode content is preserved."""
        output_path = tmp_path / "output.jsonl"
        records = iter([{"text": "Hello 世界 🌍"}])

        write_records(records, output_path, "jsonl")

        line = output_path.read_text().strip()
        data = json.loads(line)
        assert data["text"] == "Hello 世界 🌍"


class TestFormatRecord:
    """Tests for format_record function."""

    def test_format_json(self):
        """Test formatting as JSON."""
        record = {"id": 1, "name": "test"}

        result = format_record(record, "json")

        assert json.loads(result) == record

    def test_format_yaml(self):
        """Test formatting as YAML."""
        record = {"id": 1, "name": "test"}

        result = format_record(record, "yaml")

        assert yaml.safe_load(result) == record

    def test_default_is_json(self):
        """Test that default format is JSON."""
        record = {"id": 1}

        result = format_record(record)

        assert json.loads(result) == record
