"""RunScriptsProvider — enrichment provider fetching run scripts from SWE-bench Pro OS repo."""

from __future__ import annotations

import logging
from typing import Any, Iterator

from ee_bench_generator import Provider
from ee_bench_generator.errors import ProviderError
from ee_bench_generator.metadata import Context, FieldDescriptor, ProviderMetadata

logger = logging.getLogger(__name__)


class RunScriptsProvider(Provider):
    """Enrichment-only provider that fetches run_script.sh and parser.py from a source repo.

    Reads ``instance_id`` from the current item (via ``item_mapping``) and
    looks up the matching directory under ``run_scripts/`` in the configured
    GitHub repository (default: ``scaleapi/SWE-bench_Pro-os``).

    **Not a primary provider** — calling :meth:`iter_items` will raise
    :class:`~ee_bench_generator.errors.ProviderError`.
    """

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            name="run_scripts",
            sources=["run_scripts"],
            provided_fields=[
                FieldDescriptor(
                    "run_script",
                    source="run_scripts",
                    description="Content of run_script.sh",
                ),
                FieldDescriptor(
                    "parser_script",
                    source="run_scripts",
                    description="Content of parser.py",
                ),
                FieldDescriptor(
                    "run_script_name",
                    source="run_scripts",
                    description="Filename run_script.sh or empty string",
                ),
                FieldDescriptor(
                    "parser_name",
                    source="run_scripts",
                    description="Filename parser.py or empty string",
                ),
            ],
        )

    def prepare(self, **options: Any) -> None:
        """Prepare provider by building instance_id → directory mapping.

        Options:
            repo: Source GitHub repo (default ``scaleapi/SWE-bench_Pro-os``).
            github_token: GitHub PAT for API access.
            scripts_dir: Directory in the repo containing run scripts (default ``run_scripts``).
        """
        from github import Github

        repo_name = options.get("repo", "scaleapi/SWE-bench_Pro-os")
        github_token = options.get("github_token", "")
        self._scripts_dir = options.get("scripts_dir", "run_scripts")

        gh = Github(github_token) if github_token else Github()
        self._repo = gh.get_repo(repo_name)

        # Build mapping: instance_id → directory name
        # Directories are named like "instance_id" or "instance_id-vnan"
        self._instance_to_dir: dict[str, str] = {}
        try:
            contents = self._repo.get_contents(self._scripts_dir)
            if not isinstance(contents, list):
                contents = [contents]
            for item in contents:
                if item.type == "dir":
                    dir_name = item.name
                    # Strip version suffix like "-vnan" for matching
                    instance_id = dir_name.rsplit("-v", 1)[0] if "-v" in dir_name else dir_name
                    self._instance_to_dir[instance_id] = dir_name
        except Exception as e:
            logger.warning("Failed to list %s in %s: %s", self._scripts_dir, repo_name, e)

        # Cache for fetched file contents: directory_name → {filename: content}
        self._content_cache: dict[str, dict[str, str]] = {}

        logger.info(
            "RunScriptsProvider: mapped %d instance directories from %s/%s",
            len(self._instance_to_dir),
            repo_name,
            self._scripts_dir,
        )

    def iter_items(self, context: Context) -> Iterator[dict[str, Any]]:  # noqa: ARG002
        raise ProviderError(
            "RunScriptsProvider is an enrichment-only provider and cannot "
            "be used as a primary provider. Use it with item_mapping in a "
            "multi-provider configuration."
        )

    def get_field(self, name: str, source: str, context: Context) -> Any:  # noqa: ARG002
        valid_fields = ("run_script", "parser_script", "run_script_name", "parser_name")
        if name not in valid_fields:
            raise ProviderError(
                f"RunScriptsProvider does not provide field '{name}'"
            )

        current = context.current_item or {}
        instance_id = current.get("instance_id", "")

        if not instance_id:
            return ""

        dir_name = self._instance_to_dir.get(instance_id)
        if not dir_name:
            return ""

        # Lazily fetch directory contents
        files = self._fetch_directory(dir_name)

        if name == "run_script":
            return files.get("run_script.sh", "")
        elif name == "parser_script":
            return files.get("parser.py", "")
        elif name == "run_script_name":
            return "run_script.sh" if "run_script.sh" in files else ""
        elif name == "parser_name":
            return "parser.py" if "parser.py" in files else ""

        return ""

    def _fetch_directory(self, dir_name: str) -> dict[str, str]:
        """Fetch and cache all files in a run_scripts subdirectory."""
        if dir_name in self._content_cache:
            return self._content_cache[dir_name]

        files: dict[str, str] = {}
        try:
            path = f"{self._scripts_dir}/{dir_name}"
            contents = self._repo.get_contents(path)
            if not isinstance(contents, list):
                contents = [contents]
            for item in contents:
                if item.type == "file" and item.name in ("run_script.sh", "parser.py", "instance_info.txt"):
                    files[item.name] = item.decoded_content.decode("utf-8")
        except Exception as e:
            logger.warning("Failed to fetch %s/%s: %s", self._scripts_dir, dir_name, e)

        self._content_cache[dir_name] = files
        return files
