"""GitHubAttachmentGenerator — attaches run script files to existing PR branches."""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator

from ee_bench_generator import Generator, Provider
from ee_bench_generator.metadata import Context, FieldDescriptor, GeneratorMetadata

logger = logging.getLogger(__name__)


class GitHubAttachmentGenerator(Generator):
    """Generator that attaches files to existing PR branches and updates PR metadata.

    For each dataset item with run scripts available:
    1. Looks up the fork repo and existing PR branch
    2. Adds files under a configurable directory (default ``.swe-bench-pro/``)
    3. Updates the PR body metadata block with file names
    """

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="github_attachment",
            required_fields=[
                FieldDescriptor("instance_id", description="Unique task identifier"),
                FieldDescriptor("repo", description="Upstream repository (owner/name)"),
            ],
            optional_fields=[
                FieldDescriptor("run_script", required=False, description="Content of run_script.sh"),
                FieldDescriptor("parser_script", required=False, description="Content of parser.py"),
                FieldDescriptor("run_script_name", required=False, description="Filename run_script.sh or empty"),
                FieldDescriptor("parser_name", required=False, description="Filename parser.py or empty"),
            ],
        )

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        from github import Github, InputGitTreeElement

        from ee_bench_importer.pr_body import parse_metadata_block, update_metadata_in_body

        gen_opts = context.options.get("generator_options", {})
        target_org = gen_opts.get("target_org", "dpaia")
        github_token = gen_opts.get("github_token", "")
        dataset_label = gen_opts.get("dataset_label", "swe-bench-pro")
        attachment_dir = gen_opts.get("attachment_dir", ".swe-bench-pro")
        state_file = gen_opts.get("state_file")
        delay = float(gen_opts.get("inter_operation_delay", 0.5))
        dry_run = gen_opts.get("dry_run", False)

        if not github_token and not dry_run:
            raise ValueError("github_token is required for non-dry-run attachment uploads")

        gh = None
        if not dry_run:
            gh = Github(github_token)

        # Cache for fork repos
        fork_cache: dict[str, Any] = {}

        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            instance_id = provider.get_field("instance_id", "", item_context)
            upstream_repo = provider.get_field("repo", "", item_context)

            # Get run script contents (optional)
            run_script = self._get_optional(provider, "run_script", item_context, "")
            parser_script = self._get_optional(provider, "parser_script", item_context, "")
            run_script_name = self._get_optional(provider, "run_script_name", item_context, "")
            parser_name = self._get_optional(provider, "parser_name", item_context, "")

            if not run_script and not parser_script:
                yield {
                    "instance_id": instance_id,
                    "status": "skipped",
                    "files": [],
                    "pr_url": "",
                    "reason": "no_run_scripts",
                    "error": "",
                }
                continue

            if dry_run:
                files = []
                if run_script:
                    files.append(f"{attachment_dir}/run_script.sh")
                if parser_script:
                    files.append(f"{attachment_dir}/parser.py")
                logger.info("[DRY RUN] Would attach %s to %s", files, instance_id)
                yield {
                    "instance_id": instance_id,
                    "status": "dry_run_attached",
                    "files": files,
                    "pr_url": "",
                    "reason": "",
                    "error": "",
                }
                continue

            try:
                result = self._attach_files(
                    gh=gh,
                    instance_id=instance_id,
                    upstream_repo=upstream_repo,
                    target_org=target_org,
                    dataset_label=dataset_label,
                    attachment_dir=attachment_dir,
                    run_script=run_script,
                    parser_script=parser_script,
                    run_script_name=run_script_name,
                    parser_name=parser_name,
                    fork_cache=fork_cache,
                )
                yield result
            except Exception as e:
                logger.error("Failed to attach files for %s: %s", instance_id, e)
                yield {
                    "instance_id": instance_id,
                    "status": "error",
                    "files": [],
                    "pr_url": "",
                    "reason": "",
                    "error": str(e),
                }

            if delay > 0:
                time.sleep(delay)

    def _attach_files(
        self,
        gh: Any,
        instance_id: str,
        upstream_repo: str,
        target_org: str,
        dataset_label: str,
        attachment_dir: str,
        run_script: str,
        parser_script: str,
        run_script_name: str,
        parser_name: str,
        fork_cache: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach files to an existing PR branch."""
        from github import InputGitTreeElement

        from ee_bench_importer.pr_body import parse_metadata_block, update_metadata_in_body

        # Get the fork repo
        repo_name = upstream_repo.split("/")[-1]
        fork_full_name = f"{target_org}/{repo_name}"

        if fork_full_name not in fork_cache:
            fork_cache[fork_full_name] = gh.get_repo(fork_full_name)
        fork_repo = fork_cache[fork_full_name]

        # Get the after branch
        branch_name = f"{dataset_label}/{instance_id}/after"
        try:
            ref = fork_repo.get_git_ref(f"heads/{branch_name}")
        except Exception as e:
            raise ValueError(
                f"Branch '{branch_name}' not found in {fork_full_name}: {e}"
            )

        # Get current commit and tree
        current_sha = ref.object.sha
        current_commit = fork_repo.get_git_commit(current_sha)

        # Build tree elements for new files
        tree_elements = []
        attached_files = []

        if run_script:
            blob = fork_repo.create_git_blob(run_script, "utf-8")
            tree_elements.append(
                InputGitTreeElement(
                    path=f"{attachment_dir}/run_script.sh",
                    mode="100755",
                    type="blob",
                    sha=blob.sha,
                )
            )
            attached_files.append(f"{attachment_dir}/run_script.sh")

        if parser_script:
            blob = fork_repo.create_git_blob(parser_script, "utf-8")
            tree_elements.append(
                InputGitTreeElement(
                    path=f"{attachment_dir}/parser.py",
                    mode="100644",
                    type="blob",
                    sha=blob.sha,
                )
            )
            attached_files.append(f"{attachment_dir}/parser.py")

        if not tree_elements:
            return {
                "instance_id": instance_id,
                "status": "skipped",
                "files": [],
                "pr_url": "",
                "reason": "no_files_to_attach",
                "error": "",
            }

        # Create new tree and commit
        new_tree = fork_repo.create_git_tree(tree_elements, current_commit.tree)
        new_commit = fork_repo.create_git_commit(
            message=f"Add run scripts for {instance_id}",
            tree=new_tree,
            parents=[current_commit],
        )

        # Update branch ref
        ref.edit(sha=new_commit.sha, force=True)

        # Find the PR for this branch and update metadata
        pr_url = ""
        branch_after = f"{dataset_label}/{instance_id}/after"
        try:
            head_ref = f"{fork_repo.owner.login}:{branch_after}"
            pulls = fork_repo.get_pulls(state="all", head=head_ref)
            for pr in pulls:
                # Update PR body metadata with file names
                body = pr.body or ""
                existing_meta = parse_metadata_block(body)
                if run_script_name:
                    existing_meta["run_script_name"] = run_script_name
                if parser_name:
                    existing_meta["parser_name"] = parser_name
                new_body = update_metadata_in_body(body, existing_meta)
                pr.edit(body=new_body)
                pr_url = pr.html_url
                break
        except Exception as e:
            logger.warning("Failed to update PR metadata for %s: %s", instance_id, e)

        return {
            "instance_id": instance_id,
            "status": "attached",
            "files": attached_files,
            "pr_url": pr_url,
            "reason": "",
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
