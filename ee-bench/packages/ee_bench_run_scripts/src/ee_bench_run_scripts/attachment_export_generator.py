"""AttachmentExportGenerator — downloads attachment files from PR branches to local folders."""

from __future__ import annotations

import logging
import os
from typing import Any, Iterator

from ee_bench_generator import Generator, Provider
from ee_bench_generator.metadata import Context, FieldDescriptor, GeneratorMetadata

logger = logging.getLogger(__name__)


class AttachmentExportGenerator(Generator):
    """Generator that downloads attachment files from PR branches to local folders.

    For each PR with attachments:
    1. Looks up the ``after`` branch for the instance
    2. Lists files in the attachment directory (default ``.swe-bench-pro/``)
    3. Downloads each file to ``{output_dir}/{instance_id}/``
    """

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="attachment_export",
            required_fields=[
                FieldDescriptor("repo_url", description="Repository clone URL"),
            ],
            optional_fields=[
                FieldDescriptor("instance_id", required=False, description="Instance ID from metadata enrichment"),
                FieldDescriptor("run_script_name", required=False, description="Filename of run script from metadata"),
                FieldDescriptor("parser_name", required=False, description="Filename of parser from metadata"),
            ],
        )

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        from github import Github

        gen_opts = context.options.get("generator_options", {})
        github_token = gen_opts.get("github_token", "")
        dataset_label = gen_opts.get("dataset_label", "swe-bench-pro")
        attachment_dir = gen_opts.get("attachment_dir", ".swe-bench-pro")
        output_dir = gen_opts.get("output_dir", "attachments")
        dry_run = gen_opts.get("dry_run", False)

        if not github_token and not dry_run:
            raise ValueError("github_token is required for non-dry-run attachment export")

        gh = None
        if not dry_run:
            gh = Github(github_token)

        # Cache for repo objects
        repo_cache: dict[str, Any] = {}

        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            instance_id = self._get_optional(
                provider, "instance_id", item_context, ""
            )
            if not instance_id:
                continue

            repo_url = provider.get_field("repo_url", "", item_context)

            if dry_run:
                logger.info("[DRY RUN] Would export attachments for %s", instance_id)
                yield {
                    "instance_id": instance_id,
                    "status": "dry_run_downloaded",
                    "output_dir": f"{output_dir}/{instance_id}",
                    "files": [],
                    "error": "",
                }
                continue

            try:
                result = self._export_attachments(
                    gh=gh,
                    instance_id=instance_id,
                    repo_url=repo_url,
                    dataset_label=dataset_label,
                    attachment_dir=attachment_dir,
                    output_dir=output_dir,
                    repo_cache=repo_cache,
                )
                yield result
            except Exception as e:
                logger.error("Failed to export attachments for %s: %s", instance_id, e)
                yield {
                    "instance_id": instance_id,
                    "status": "error",
                    "output_dir": "",
                    "files": [],
                    "error": str(e),
                }

    def _export_attachments(
        self,
        gh: Any,
        instance_id: str,
        repo_url: str,
        dataset_label: str,
        attachment_dir: str,
        output_dir: str,
        repo_cache: dict[str, Any],
    ) -> dict[str, Any]:
        """Download attachment files from a PR branch."""
        # Extract repo full name from URL (e.g., "https://github.com/dpaia/repo" -> "dpaia/repo")
        repo_full_name = repo_url.rstrip("/").split("github.com/")[-1]
        if repo_full_name.endswith(".git"):
            repo_full_name = repo_full_name[:-4]

        if repo_full_name not in repo_cache:
            repo_cache[repo_full_name] = gh.get_repo(repo_full_name)
        repo = repo_cache[repo_full_name]

        branch_name = f"{dataset_label}/{instance_id}/after"

        # Try to list the attachment directory on the branch
        try:
            contents = repo.get_contents(attachment_dir, ref=branch_name)
        except Exception:
            return {
                "instance_id": instance_id,
                "status": "no_attachments",
                "output_dir": "",
                "files": [],
                "error": "",
            }

        if not isinstance(contents, list):
            contents = [contents]

        if not contents:
            return {
                "instance_id": instance_id,
                "status": "no_attachments",
                "output_dir": "",
                "files": [],
                "error": "",
            }

        # Create output directory
        instance_output_dir = os.path.join(output_dir, instance_id)
        os.makedirs(instance_output_dir, exist_ok=True)

        downloaded_files = []
        for file_content in contents:
            if file_content.type != "file":
                continue

            file_path = os.path.join(instance_output_dir, file_content.name)
            content = file_content.decoded_content
            with open(file_path, "wb") as f:
                f.write(content)
            downloaded_files.append(file_content.name)
            logger.info("Downloaded %s/%s", instance_id, file_content.name)

        return {
            "instance_id": instance_id,
            "status": "downloaded",
            "output_dir": instance_output_dir,
            "files": downloaded_files,
            "error": "",
        }

    @staticmethod
    def _get_optional(
        provider: Provider,
        name: str,
        context: Context,
        default: Any,
    ) -> Any:
        """Get an optional field from the provider (source-less lookup)."""
        if provider.metadata.can_provide(name, ""):
            try:
                return provider.get_field(name, "", context)
            except Exception:
                return default
        return default
