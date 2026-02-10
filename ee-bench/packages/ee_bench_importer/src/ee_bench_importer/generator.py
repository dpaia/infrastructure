"""GitHub PR Importer Generator.

Creates GitHub forks, branches, PRs, labels, and project assignments
from dataset items provided by a HuggingFace dataset provider.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

from ee_bench_generator import Generator, Provider
from ee_bench_generator.clock import now_iso8601_utc
from ee_bench_generator.metadata import Context, FieldDescriptor, GeneratorMetadata
from ee_bench_generator.templates import render_template

from ee_bench_importer.patch_applier import apply_patches_via_api
from ee_bench_importer.pr_body import (
    build_pr_body,
    render_pr_body_template,
    render_pr_title_template,
    resolve_metadata_fields,
    update_metadata_in_body,
)
from ee_bench_importer.project_manager import ProjectManager
from ee_bench_importer.sync_state import (
    ImportState,
    check_sync_status,
    load_state,
    save_state,
    update_item_state,
)

logger = logging.getLogger(__name__)


def _expand_value(value: Any) -> list[str]:
    """Expand a value into a list of strings.

    Handles:
    - Python list → each element as a string
    - JSON array string (e.g., '["a","b"]') → parsed and expanded
    - Scalar → single-element list
    """
    if isinstance(value, list):
        return [str(v) for v in value if v]
    s = str(value).strip()
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
        except (json.JSONDecodeError, TypeError):
            pass
    return [s] if s else []


class GitHubPRImporterGenerator(Generator):
    """Generator that imports dataset items as GitHub Pull Requests.

    For each dataset item:
    1. Check sync state — skip if unchanged
    2. Fork upstream repo into target org (idempotent)
    3. Set repo topics from config
    4. Apply golden + test patches via Git Data API
    5. Create branch and PR with structured metadata body
    6. Add labels and project assignments
    7. Update sync state and yield status record
    """

    @property
    def metadata(self) -> GeneratorMetadata:
        return GeneratorMetadata(
            name="github_pr_importer",
            required_fields=[
                FieldDescriptor(
                    "instance_id",
                    source="dataset_item",
                    description="Unique task identifier",
                ),
                FieldDescriptor(
                    "repo",
                    source="dataset_item",
                    description="Upstream repository (owner/name)",
                ),
                FieldDescriptor(
                    "base_commit",
                    source="dataset_item",
                    description="Base commit SHA",
                ),
                FieldDescriptor(
                    "patch",
                    source="dataset_item",
                    description="Golden patch (unified diff)",
                ),
                FieldDescriptor(
                    "problem_statement",
                    source="dataset_item",
                    description="Problem description text",
                ),
                FieldDescriptor(
                    "checksum",
                    source="dataset_metadata",
                    description="SHA-256 checksum of the dataset row",
                ),
            ],
            optional_fields=[
                FieldDescriptor(
                    "test_patch",
                    source="dataset_item",
                    required=False,
                    description="Test patch (unified diff)",
                ),
                FieldDescriptor(
                    "hints_text",
                    source="dataset_item",
                    required=False,
                    description="Hints for solving the problem",
                ),
                FieldDescriptor(
                    "repo_language",
                    source="dataset_item",
                    required=False,
                    description="Programming language",
                ),
                FieldDescriptor(
                    "version",
                    source="dataset_item",
                    required=False,
                    description="Version string",
                ),
            ],
        )

    def output_schema(self) -> dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "Import Result Record",
            "required": ["instance_id", "status"],
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "Task identifier",
                },
                "status": {
                    "type": "string",
                    "enum": ["created", "updated", "skipped", "error"],
                    "description": "Import status",
                },
                "pr_url": {
                    "type": "string",
                    "description": "URL to the created/updated PR",
                },
                "pr_number": {
                    "type": ["integer", "null"],
                    "description": "PR number",
                },
                "fork_repo": {
                    "type": "string",
                    "description": "Full name of the fork repository",
                },
                "error": {
                    "type": "string",
                    "description": "Error message if status is error",
                },
            },
        }

    def generate(
        self, provider: Provider, context: Context
    ) -> Iterator[dict[str, Any]]:
        """Generate import results by creating GitHub PRs from dataset items.

        Args:
            provider: Data provider (HuggingFace dataset).
            context: Runtime context with generator options.

        Yields:
            Import result records.
        """
        gen_opts = context.options.get("generator_options", {})
        target_org = gen_opts.get("target_org", "dpaia")
        github_token = gen_opts.get("github_token", "")
        dataset_label = gen_opts.get("dataset_label", "swe-bench-pro")
        state_file = gen_opts.get("state_file", ".state/import-state.json")
        dry_run = gen_opts.get("dry_run", False)
        delay = float(gen_opts.get("inter_operation_delay", 1.0))
        metadata_fields_config = gen_opts.get("metadata_fields", [])
        pr_body_template = gen_opts.get("pr_body_template")
        pr_title_template = gen_opts.get("pr_title_template")
        labels_config = gen_opts.get("labels", [])
        topics_config = gen_opts.get("repo_topics", [])
        projects_config = gen_opts.get("projects", [])
        repo_visibility = gen_opts.get("repo_visibility")  # "public" or "private"
        project_visibility = gen_opts.get("project_visibility")  # "PUBLIC", "PRIVATE", "ORG"
        pr_state = gen_opts.get("pr_state", "open")  # "open" or "closed"

        if not github_token and not dry_run:
            raise ValueError("github_token is required for non-dry-run imports")

        # Initialize GitHub client
        github_client = None
        project_manager = None
        if not dry_run:
            from github import Github

            github_client = Github(github_token)
            project_manager = ProjectManager(github_client)

        # Load sync state
        state = load_state(state_file)
        state.dataset = dataset_label

        # Cache for fork repos (upstream_repo -> PyGithub repo object)
        fork_cache: dict[str, Any] = {}

        for item in provider.iter_items(context):
            item_context = Context(
                selection=context.selection,
                options=context.options,
                current_item=item,
            )

            instance_id = provider.get_field("instance_id", "dataset_item", item_context)
            checksum = provider.get_field("checksum", "dataset_metadata", item_context)

            # Check sync status
            sync_status = check_sync_status(state, instance_id, checksum)

            if sync_status == "skip":
                logger.info("Skipping %s (unchanged)", instance_id)
                yield {
                    "instance_id": instance_id,
                    "status": "skipped",
                    "pr_url": state.items[instance_id].pr_url,
                    "pr_number": state.items[instance_id].pr_number,
                    "fork_repo": state.items[instance_id].fork_repo,
                    "error": "",
                }
                continue

            if dry_run:
                logger.info("[DRY RUN] Would %s: %s", sync_status, instance_id)
                yield {
                    "instance_id": instance_id,
                    "status": f"dry_run_{sync_status}",
                    "pr_url": "",
                    "pr_number": None,
                    "fork_repo": "",
                    "error": "",
                }
                continue

            # Perform the import
            try:
                result = self._import_item(
                    provider=provider,
                    context=item_context,
                    github_client=github_client,
                    project_manager=project_manager,
                    target_org=target_org,
                    dataset_label=dataset_label,
                    metadata_fields_config=metadata_fields_config,
                    pr_body_template=pr_body_template,
                    pr_title_template=pr_title_template,
                    labels_config=labels_config,
                    topics_config=topics_config,
                    projects_config=projects_config,
                    sync_status=sync_status,
                    state=state,
                    fork_cache=fork_cache,
                    repo_visibility=repo_visibility,
                    project_visibility=project_visibility,
                    pr_state=pr_state,
                )

                update_item_state(
                    state,
                    instance_id,
                    checksum=checksum,
                    pr_number=result["pr_number"],
                    pr_url=result["pr_url"],
                    fork_repo=result["fork_repo"],
                    status=result["status"],
                )
                save_state(state, state_file)

                yield result

            except Exception as e:
                logger.error("Failed to import %s: %s", instance_id, e)
                update_item_state(
                    state,
                    instance_id,
                    checksum=checksum,
                    status="error",
                )
                save_state(state, state_file)

                yield {
                    "instance_id": instance_id,
                    "status": "error",
                    "pr_url": "",
                    "pr_number": None,
                    "fork_repo": "",
                    "error": str(e),
                }

            # Rate limit delay
            if delay > 0:
                time.sleep(delay)

    def _import_item(
        self,
        provider: Provider,
        context: Context,
        github_client: Any,
        project_manager: ProjectManager | None,
        target_org: str,
        dataset_label: str,
        metadata_fields_config: list,
        pr_body_template: str | None = None,
        pr_title_template: str | None = None,
        labels_config: list | None = None,
        topics_config: list | None = None,
        projects_config: list | None = None,
        sync_status: str = "create",
        state: ImportState | None = None,
        fork_cache: dict[str, Any] | None = None,
        repo_visibility: str | None = None,
        project_visibility: str | None = None,
        pr_state: str = "open",
    ) -> dict[str, Any]:
        """Import a single dataset item as a GitHub PR.

        Args:
            repo_visibility: Set fork visibility ("public" or "private").
            project_visibility: Set project visibility ("PUBLIC", "PRIVATE", "ORG").
            pr_state: PR state after creation ("open" or "closed").

        Returns:
            Result dict with instance_id, status, pr_url, pr_number, fork_repo, error.
        """
        labels_config = labels_config or []
        topics_config = topics_config or []
        projects_config = projects_config or []
        fork_cache = fork_cache if fork_cache is not None else {}

        item = context.current_item
        instance_id = provider.get_field("instance_id", "dataset_item", context)
        upstream_repo = provider.get_field("repo", "dataset_item", context)
        base_commit = provider.get_field("base_commit", "dataset_item", context)
        patch = provider.get_field("patch", "dataset_item", context)
        problem_statement = provider.get_field("problem_statement", "dataset_item", context)

        # Optional fields
        test_patch = self._get_optional(provider, "test_patch", "dataset_item", context, "")
        hints_text = self._get_optional(provider, "hints_text", "dataset_item", context, "")

        # 1. Fork the upstream repo into target org (idempotent)
        fork_repo = self._ensure_fork(
            github_client, upstream_repo, target_org, fork_cache
        )
        fork_full_name = fork_repo.full_name

        # 1b. Set repository visibility if configured
        if repo_visibility:
            self._set_repo_visibility(fork_repo, repo_visibility)

        # 2. Set repo topics
        if topics_config:
            resolved_topics = self._resolve_list_values(topics_config, item)
            self._set_repo_topics(fork_repo, resolved_topics)

        # 3. Build branch name
        branch_name = f"{dataset_label}/{instance_id}"

        # Try to find an existing PR for this branch (handles error recovery)
        pr = self._find_existing_pr(state, fork_repo, instance_id, branch_name)

        if pr:
            # PR exists — re-render body and title from templates
            extra_meta = {"imported_at": now_iso8601_utc()}
            if pr_body_template:
                template_vars = {**item, "dataset_label": dataset_label}
                new_body = render_pr_body_template(
                    pr_body_template, template_vars, extra_metadata=extra_meta,
                )
            else:
                metadata = resolve_metadata_fields(metadata_fields_config, item)
                metadata.update(extra_meta)
                new_body = update_metadata_in_body(pr.body or "", metadata)

            edit_kwargs: dict[str, Any] = {"body": new_body}

            if pr_title_template:
                template_vars = {**item, "dataset_label": dataset_label}
                edit_kwargs["title"] = render_pr_title_template(
                    pr_title_template, template_vars,
                )

            pr.edit(**edit_kwargs)
            result_status = "updated"
        else:
            # 4. Apply patches via Git Data API
            commit_message = (
                f"Import {instance_id}\n\n"
                f"Apply golden patch and test patch from {dataset_label}"
            )
            apply_patches_via_api(
                repo=fork_repo,
                base_commit_sha=base_commit,
                patch_text=patch,
                test_patch_text=test_patch if test_patch else None,
                commit_message=commit_message,
                branch_name=branch_name,
            )

            # 5. Build PR body with metadata
            extra_meta = {"imported_at": now_iso8601_utc()}
            if pr_body_template:
                # Jinja2 template path — item fields + dataset_label as variables
                template_vars = {**item, "dataset_label": dataset_label}
                pr_body = render_pr_body_template(
                    pr_body_template, template_vars, extra_metadata=extra_meta,
                )
            else:
                # Legacy metadata_fields path
                metadata = resolve_metadata_fields(metadata_fields_config, item)
                metadata.update(extra_meta)
                pr_body = build_pr_body(
                    problem_statement=problem_statement,
                    hints_text=hints_text,
                    metadata=metadata,
                )

            # 6. Build PR title
            if pr_title_template:
                template_vars = {**item, "dataset_label": dataset_label}
                pr_title = render_pr_title_template(pr_title_template, template_vars)
            else:
                pr_title = f"[{dataset_label}] {instance_id}"

            # 7. Create PR: after → before (only shows the patch diff)
            pr = fork_repo.create_pull(
                title=pr_title,
                body=pr_body,
                head=f"{branch_name}/after",
                base=f"{branch_name}/before",
            )
            result_status = "created"

        # 8. Add labels
        if labels_config:
            resolved_labels = self._resolve_list_values(labels_config, item)
            self._ensure_labels(fork_repo, resolved_labels)
            pr.add_to_labels(*resolved_labels)

        # 9. Add to projects
        if project_manager and projects_config:
            self._add_to_projects(
                project_manager, target_org, projects_config, item, pr,
                visibility=project_visibility,
            )

        # 10. Close PR if configured to be closed after creation
        if pr_state == "closed":
            pr.edit(state="closed")

        return {
            "instance_id": instance_id,
            "status": result_status,
            "pr_url": pr.html_url,
            "pr_number": pr.number,
            "fork_repo": fork_full_name,
            "error": "",
        }

    @staticmethod
    def _find_existing_pr(
        state: ImportState, fork_repo: Any, instance_id: str, branch_name: str
    ) -> Any | None:
        """Find an existing PR for this item (from state or by branch search).

        Returns the PyGithub PullRequest object, or None if not found.
        """
        # First check state for a known PR number
        existing = state.items.get(instance_id)
        if existing and existing.pr_number:
            try:
                return fork_repo.get_pull(existing.pr_number)
            except Exception:
                pass

        # Search by head branch name (try both /after suffix and plain name)
        for suffix in ["/after", ""]:
            try:
                head_ref = f"{fork_repo.owner.login}:{branch_name}{suffix}"
                pulls = fork_repo.get_pulls(state="all", head=head_ref)
                for pr in pulls:
                    return pr
            except Exception:
                pass

        return None

    def _ensure_fork(
        self,
        github_client: Any,
        upstream_repo: str,
        target_org: str,
        cache: dict[str, Any],
    ) -> Any:
        """Ensure the upstream repo is forked into the target org.

        Returns the fork Repository object. Checks for an existing fork first
        to avoid GitHub creating duplicates with `-1` suffixes.
        """
        if upstream_repo in cache:
            return cache[upstream_repo]

        repo = github_client.get_repo(upstream_repo)

        # Check if fork already exists in target org
        expected_name = f"{target_org}/{repo.name}"
        try:
            existing = github_client.get_repo(expected_name)
            if existing.fork:
                cache[upstream_repo] = existing
                logger.info("Fork already exists: %s", existing.full_name)
                return existing
        except Exception:
            pass  # Fork doesn't exist yet

        fork = repo.create_fork(organization=target_org)

        cache[upstream_repo] = fork
        logger.info("Fork created: %s -> %s", upstream_repo, fork.full_name)
        return fork

    def _set_repo_visibility(self, repo: Any, visibility: str) -> None:
        """Set repository visibility (public or private).

        Args:
            repo: PyGithub Repository object.
            visibility: "public" or "private".
        """
        if visibility not in ("public", "private"):
            logger.warning("Invalid repo_visibility '%s', must be 'public' or 'private'", visibility)
            return
        try:
            current_private = repo.private
            want_private = visibility == "private"
            if current_private != want_private:
                repo.edit(private=want_private)
                logger.info("Set %s visibility to %s", repo.full_name, visibility)
        except Exception as e:
            logger.warning("Failed to set visibility on %s: %s", repo.full_name, e)

    def _set_repo_topics(self, repo: Any, topics: list[str]) -> None:
        """Set topics on a repository, merging with existing ones."""
        try:
            existing = set(repo.get_topics())
            new_topics = existing | {t.lower().replace(" ", "-") for t in topics}
            repo.replace_topics(sorted(new_topics))
        except Exception as e:
            logger.warning("Failed to set topics on %s: %s", repo.full_name, e)

    def _ensure_labels(self, repo: Any, label_names: list[str]) -> None:
        """Ensure labels exist on the repository."""
        existing_labels = {label.name for label in repo.get_labels()}
        for name in label_names:
            if name not in existing_labels:
                try:
                    repo.create_label(name=name, color="ededed")
                except Exception:
                    pass  # Label may have been created concurrently

    def _add_to_projects(
        self,
        project_manager: ProjectManager,
        target_org: str,
        projects_config: list[dict[str, str]],
        item: dict[str, Any],
        pr: Any,
        visibility: str | None = None,
    ) -> None:
        """Add a PR to configured projects.

        Args:
            project_manager: ProjectManager instance.
            target_org: GitHub organization name.
            projects_config: List of project config dicts with name and scope.
            item: Current dataset item.
            pr: PyGithub PullRequest object.
            visibility: Project visibility ("PUBLIC", "PRIVATE", or "ORG").
        """
        for proj_config in projects_config:
            project_name = proj_config.get("name", "")
            if "{{" in project_name:
                project_name = render_template(project_name, item).strip()
                if not project_name:
                    continue
            elif project_name.startswith("from:"):
                # backward compat
                field_name = project_name[5:]
                project_name = str(item.get(field_name, ""))
                if not project_name:
                    continue

            if not project_name:
                continue

            try:
                project_id = project_manager.ensure_project(
                    target_org, project_name, visibility=visibility,
                )
                pr_node_id = pr.raw_data.get("node_id", "")
                if pr_node_id:
                    project_manager.add_pr_to_project(project_id, pr_node_id)
            except Exception as e:
                logger.warning(
                    "Failed to add PR to project '%s': %s", project_name, e
                )

    @staticmethod
    def _resolve_list_values(
        config_list: list[str], item: dict[str, Any]
    ) -> list[str]:
        """Resolve a list of values, supporting Jinja2 ``{{ }}`` and ``from:`` syntax.

        Args:
            config_list: List of static strings, ``"{{ field }}"`` templates,
                or legacy ``"from:field_name"`` references.
            item: Current dataset item.

        Returns:
            List of resolved string values.
        """
        result = []
        for value in config_list:
            if not isinstance(value, str):
                continue
            if "{{" in value:
                rendered = render_template(value, item).strip()
                if not rendered:
                    continue
                values = _expand_value(rendered)
                for v in values:
                    normalized = str(v).lower().replace(" ", "-").replace("+", "plus")
                    result.append(normalized)
                    if str(v) != normalized:
                        result.append(str(v))
            elif value.startswith("from:"):
                # backward compat
                field_name = value[5:]
                resolved = item.get(field_name, "")
                if not resolved:
                    continue
                # Expand: resolved may be a list, a JSON array string, or a scalar
                values = _expand_value(resolved)
                for v in values:
                    normalized = str(v).lower().replace(" ", "-").replace("+", "plus")
                    result.append(normalized)
                    # Also add the original case version for labels
                    if str(v) != normalized:
                        result.append(str(v))
            else:
                result.append(value)
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for v in result:
            if v not in seen:
                seen.add(v)
                deduped.append(v)
        return deduped

    @staticmethod
    def _get_optional(
        provider: Provider,
        name: str,
        source: str,
        context: Context,
        default: Any,
    ) -> Any:
        """Get an optional field from the provider."""
        if provider.metadata.can_provide(name, source):
            try:
                return provider.get_field(name, source, context)
            except Exception:
                return default
        return default
