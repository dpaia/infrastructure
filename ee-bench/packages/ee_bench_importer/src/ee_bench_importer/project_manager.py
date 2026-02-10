"""GitHub Projects V2 management via PyGithub GraphQL.

Creates and manages GitHub Projects V2 for organizing imported PRs.
Uses GraphQL mutations for project creation and item addition.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages GitHub Projects V2 for an organization.

    Uses PyGithub's GraphQL support to create projects and add PR items.
    Caches project IDs per run to minimize API calls.
    """

    def __init__(self, github_client) -> None:
        """Initialize with a PyGithub Github instance.

        Args:
            github_client: Authenticated PyGithub Github object.
        """
        self._github = github_client
        self._project_cache: dict[str, str] = {}  # project_name -> project_id
        self._org_id_cache: dict[str, str] = {}  # org_name -> org_node_id

    def ensure_project(
        self, org: str, project_name: str, visibility: str | None = None,
    ) -> str:
        """Ensure a project exists in the organization, creating if needed.

        Args:
            org: GitHub organization name.
            project_name: Project title.
            visibility: Project visibility when creating — "PUBLIC", "PRIVATE",
                or "ORG" (organization members only). Only applies to newly
                created projects. If None, uses GitHub's default (private).

        Returns:
            Project node ID.
        """
        cache_key = f"{org}/{project_name}"
        if cache_key in self._project_cache:
            return self._project_cache[cache_key]

        # Try to find existing project
        project_id = self._find_project(org, project_name)
        if project_id:
            self._project_cache[cache_key] = project_id
            return project_id

        # Create new project
        project_id = self._create_project(org, project_name)
        self._project_cache[cache_key] = project_id
        logger.info("Created project '%s' in %s (ID: %s)", project_name, org, project_id)

        # Set visibility if specified (must be done after creation)
        if visibility:
            self._set_project_visibility(project_id, visibility)

        return project_id

    def add_pr_to_project(self, project_id: str, pr_node_id: str) -> str | None:
        """Add a PR to a project.

        Args:
            project_id: Project node ID.
            pr_node_id: PR node ID.

        Returns:
            Project item ID, or None if failed.
        """
        query = """
        mutation($projectId: ID!, $contentId: ID!) {
            addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
                item {
                    id
                }
            }
        }
        """
        variables = {"projectId": project_id, "contentId": pr_node_id}

        try:
            result = self._graphql(query, variables)
            return result.get("addProjectV2ItemById", {}).get("item", {}).get("id")
        except Exception as e:
            logger.warning("Failed to add PR to project: %s", e)
            return None

    def _get_org_id(self, org: str) -> str:
        """Get the node ID for an organization."""
        if org in self._org_id_cache:
            return self._org_id_cache[org]

        query = """
        query($login: String!) {
            organization(login: $login) {
                id
            }
        }
        """
        result = self._graphql(query, {"login": org})
        org_id = result["organization"]["id"]
        self._org_id_cache[org] = org_id
        return org_id

    def _find_project(self, org: str, project_name: str) -> str | None:
        """Find a project by name in an organization."""
        query = """
        query($login: String!, $first: Int!) {
            organization(login: $login) {
                projectsV2(first: $first) {
                    nodes {
                        id
                        title
                    }
                }
            }
        }
        """
        result = self._graphql(query, {"login": org, "first": 100})
        projects = result.get("organization", {}).get("projectsV2", {}).get("nodes", [])

        for project in projects:
            if project["title"] == project_name:
                return project["id"]

        return None

    def _set_project_visibility(self, project_id: str, visibility: str) -> None:
        """Set the visibility of a project.

        Args:
            project_id: Project node ID.
            visibility: "PUBLIC", "PRIVATE", or "ORG".
        """
        # GitHub Projects V2 visibility is set via updateProjectV2 mutation
        # Valid values: PUBLIC, PRIVATE (ORG is treated as PRIVATE with org access)
        gql_visibility = visibility.upper()
        if gql_visibility == "ORG":
            gql_visibility = "PRIVATE"
        if gql_visibility not in ("PUBLIC", "PRIVATE"):
            logger.warning("Invalid project_visibility '%s', skipping", visibility)
            return

        query = """
        mutation($projectId: ID!, $public: Boolean!) {
            updateProjectV2(input: {projectId: $projectId, public: $public}) {
                projectV2 {
                    id
                }
            }
        }
        """
        is_public = gql_visibility == "PUBLIC"
        try:
            self._graphql(query, {"projectId": project_id, "public": is_public})
            logger.info("Set project %s visibility to %s", project_id, visibility)
        except Exception as e:
            logger.warning("Failed to set project visibility: %s", e)

    def _create_project(self, org: str, project_name: str) -> str:
        """Create a new project in an organization."""
        org_id = self._get_org_id(org)

        query = """
        mutation($ownerId: ID!, $title: String!) {
            createProjectV2(input: {ownerId: $ownerId, title: $title}) {
                projectV2 {
                    id
                }
            }
        }
        """
        result = self._graphql(query, {"ownerId": org_id, "title": project_name})
        return result["createProjectV2"]["projectV2"]["id"]

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute a GraphQL query via PyGithub.

        Args:
            query: GraphQL query string.
            variables: Query variables.

        Returns:
            Response data dict.

        Raises:
            Exception: If the query fails or returns errors.
        """
        # PyGithub exposes _Github__requester for raw requests
        headers, data = self._github._Github__requester.graphql_query(query, variables)

        if "errors" in data:
            errors = data["errors"]
            msg = "; ".join(e.get("message", str(e)) for e in errors)
            raise Exception(f"GraphQL error: {msg}")

        return data.get("data", {})
