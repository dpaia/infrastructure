"""Build system detection utilities for JVM projects.

This module provides functions to detect the build system used in a repository
by searching for build configuration files (pom.xml, build.gradle, build.gradle.kts).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ee_bench_github.api import GitHubAPIClient

logger = logging.getLogger(__name__)


# Build system constants
BUILD_SYSTEM_MAVEN = "maven"
BUILD_SYSTEM_GRADLE = "gradle"
BUILD_SYSTEM_GRADLE_KOTLIN = "gradle-kotlin"
BUILD_SYSTEM_UNKNOWN = ""


def detect_build_system(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    commit: str | None = None,
) -> str:
    """Detect the build system used in a repository.

    Searches for build configuration files at a specific commit or HEAD.

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        commit: Optional commit SHA to check. If None, uses HEAD.

    Returns:
        Build system identifier:
        - "maven" if Maven is detected (pom.xml exists)
        - "gradle-kotlin" if Gradle with Kotlin DSL is detected
        - "gradle" if Gradle with Groovy DSL is detected
        - "" (empty string) if no build system is detected
    """
    tree_ref = commit if commit else "HEAD"

    logger.debug(f"Detecting build system for {owner}/{repo} at {tree_ref}")

    try:
        # Search for Maven build files
        maven_files = _find_files_by_name(client, owner, repo, "pom.xml", tree_ref)
        if maven_files:
            logger.debug(f"Maven detected: {len(maven_files)} pom.xml file(s)")
            return BUILD_SYSTEM_MAVEN

        # Search for Gradle build files
        gradle_groovy_files = _find_files_by_name(
            client, owner, repo, "build.gradle", tree_ref
        )
        gradle_kotlin_files = _find_files_by_name(
            client, owner, repo, "build.gradle.kts", tree_ref
        )

        if gradle_groovy_files or gradle_kotlin_files:
            # If both types exist, prioritize based on count
            # If equal, prioritize Kotlin as it's more modern
            groovy_count = len(gradle_groovy_files)
            kotlin_count = len(gradle_kotlin_files)

            if kotlin_count >= groovy_count:
                logger.debug(
                    f"Gradle Kotlin detected: {kotlin_count} build.gradle.kts file(s)"
                )
                return BUILD_SYSTEM_GRADLE_KOTLIN
            else:
                logger.debug(
                    f"Gradle Groovy detected: {groovy_count} build.gradle file(s)"
                )
                return BUILD_SYSTEM_GRADLE

        logger.debug("No build system detected")
        return BUILD_SYSTEM_UNKNOWN

    except Exception as e:
        logger.warning(f"Failed to detect build system: {e}")
        return BUILD_SYSTEM_UNKNOWN


def _find_files_by_name(
    client: GitHubAPIClient,
    owner: str,
    repo: str,
    filename: str,
    tree_ref: str,
) -> list[str]:
    """Find files with a specific name in the repository tree.

    Uses GitHub's tree API to search for files at a specific commit.

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        filename: Filename to search for (e.g., "pom.xml").
        tree_ref: Git tree reference (commit SHA or "HEAD").

    Returns:
        List of file paths matching the filename.
    """
    try:
        # Get the repository tree (non-recursive for root level)
        # This is a simple approach - we check root level first
        tree_data = client.get(
            f"/repos/{owner}/{repo}/git/trees/{tree_ref}",
            recursive="true",
        )

        files = []
        for item in tree_data.get("tree", []):
            if item.get("type") == "blob":
                path = item.get("path", "")
                # Check if the filename matches
                if path == filename or path.endswith(f"/{filename}"):
                    files.append(path)

        return files

    except Exception as e:
        logger.debug(f"Failed to search for {filename}: {e}")
        return []


def is_maven_project(build_system: str) -> bool:
    """Check if the build system is Maven.

    Args:
        build_system: Build system identifier from detect_build_system().

    Returns:
        True if Maven, False otherwise.
    """
    return build_system == BUILD_SYSTEM_MAVEN


def is_gradle_project(build_system: str) -> bool:
    """Check if the build system is Gradle (any variant).

    Args:
        build_system: Build system identifier from detect_build_system().

    Returns:
        True if Gradle (Groovy or Kotlin DSL), False otherwise.
    """
    return build_system in (BUILD_SYSTEM_GRADLE, BUILD_SYSTEM_GRADLE_KOTLIN)
