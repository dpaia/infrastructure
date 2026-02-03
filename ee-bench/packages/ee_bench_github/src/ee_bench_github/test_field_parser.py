"""Parser for extracting FAIL_TO_PASS, PASS_TO_PASS, and METADATA test fields from text.

This module provides functions to parse test field information from:
- Issue bodies
- Issue comments
- PR bodies
- Commit messages
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ee_bench_github.api import GitHubAPIClient

logger = logging.getLogger(__name__)


@dataclass
class ParsedTestFields:
    """Container for parsed test fields.

    Attributes:
        fail_to_pass: JSON array string of tests that should fail then pass.
        pass_to_pass: JSON array string of tests that should always pass.
        metadata: Optional metadata string (raw value, not JSON normalized).
        source_id: Optional identifier of the source (e.g., comment ID).
    """

    fail_to_pass: str
    pass_to_pass: str
    metadata: str = ""
    source_id: str = ""


@dataclass
class TextSource:
    """A text source to search for test fields.

    Attributes:
        text: The text content to search.
        source_id: Optional identifier (e.g., comment ID, "issue_body").
        priority: Higher priority sources are checked first.
    """

    text: str
    source_id: str = ""
    priority: int = 0


def parse_test_fields(text: str) -> ParsedTestFields:
    """Parse FAIL_TO_PASS and PASS_TO_PASS fields from text.

    Supports multiple formats:
    - Inline JSON: `FAIL_TO_PASS: ["test1", "test2"]`
    - Comma-separated: `FAIL_TO_PASS: test1, test2`
    - Header style: `## FAIL_TO_PASS\\n["test1"]`
    - Case-insensitive markers

    Args:
        text: Text to parse (typically PR body).

    Returns:
        ParsedTestFields with JSON array strings for both fields.
        Returns "[]" for fields not found.

    Example:
        >>> result = parse_test_fields("FAIL_TO_PASS: test1, test2")
        >>> result.fail_to_pass
        '["test1", "test2"]'
    """
    fail_to_pass = _extract_field(text, "FAIL_TO_PASS")
    pass_to_pass = _extract_field(text, "PASS_TO_PASS")

    return ParsedTestFields(
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
    )


def _extract_field(text: str, field_name: str) -> str:
    """Extract a single test field from text.

    Args:
        text: Text to search.
        field_name: Field name (e.g., "FAIL_TO_PASS").

    Returns:
        JSON array string, or "[]" if not found.
    """
    if not text:
        return "[]"

    # Pattern 1: Header style - ## FIELD_NAME followed by content on next line(s)
    header_pattern = rf"(?:^|\n)##\s*{field_name}\s*\n(.*?)(?=\n##|\n\n|\Z)"
    header_match = re.search(header_pattern, text, re.IGNORECASE | re.DOTALL)
    if header_match:
        value = header_match.group(1).strip()
        return _normalize_value(value)

    # Pattern 2: Inline - FIELD_NAME: value (on same line or next)
    # Use [ \t]* instead of \s* to avoid consuming newlines
    inline_pattern = rf"(?:^|\n)\s*{field_name}\s*:[ \t]*(.*?)(?=\n[A-Z_]+:|\n\n|\n##|\Z)"
    inline_match = re.search(inline_pattern, text, re.IGNORECASE | re.DOTALL)
    if inline_match:
        value = inline_match.group(1).strip()
        return _normalize_value(value)

    # Pattern 3: Simple inline on same line
    simple_pattern = rf"{field_name}\s*:[ \t]*(.*?)(?:\n|$)"
    simple_match = re.search(simple_pattern, text, re.IGNORECASE)
    if simple_match:
        value = simple_match.group(1).strip()
        return _normalize_value(value)

    return "[]"


def _normalize_value(value: str) -> str:
    """Normalize a field value to JSON array string.

    Args:
        value: Raw extracted value.

    Returns:
        JSON array string.
    """
    if not value:
        return "[]"

    # Remove markdown code block markers
    value = re.sub(r"^```\w*\n?", "", value)
    value = re.sub(r"\n?```$", "", value)
    value = value.strip()

    if not value:
        return "[]"

    # Try parsing as JSON first
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return json.dumps(parsed)
        # Single value - wrap in list
        return json.dumps([str(parsed)])
    except json.JSONDecodeError:
        pass

    # Check if it looks like a JSON array but malformed
    if value.startswith("[") and value.endswith("]"):
        # Try to fix common issues
        try:
            # Replace single quotes with double quotes
            fixed = value.replace("'", '"')
            parsed = json.loads(fixed)
            if isinstance(parsed, list):
                return json.dumps(parsed)
        except json.JSONDecodeError:
            pass

    # Parse as comma-separated list
    items = []
    for item in value.split(","):
        item = item.strip()
        # Remove surrounding quotes if present
        if (item.startswith('"') and item.endswith('"')) or (
            item.startswith("'") and item.endswith("'")
        ):
            item = item[1:-1]
        if item:
            items.append(item)

    return json.dumps(items) if items else "[]"


def extract_metadata(text: str) -> str:
    """Extract METADATA field from text.

    The METADATA field is only extracted if FAIL_TO_PASS or PASS_TO_PASS
    is also present in the same text block.

    Args:
        text: Text to search.

    Returns:
        Raw metadata value, or empty string if not found.
    """
    if not text:
        return ""

    # Only extract METADATA if test fields are present
    has_test_fields = (
        re.search(r"FAIL_TO_PASS\s*:", text, re.IGNORECASE)
        or re.search(r"PASS_TO_PASS\s*:", text, re.IGNORECASE)
    )
    if not has_test_fields:
        return ""

    # Pattern for METADATA field
    metadata_pattern = r"METADATA\s*:[ \t]*(.*?)(?:\n|$)"
    match = re.search(metadata_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return ""


def parse_test_fields_from_sources(
    sources: list[TextSource],
) -> ParsedTestFields:
    """Parse test fields from multiple text sources.

    Searches through sources in priority order (highest first) and returns
    the first found test fields. This allows checking issue comments before
    the issue body, for example.

    Args:
        sources: List of TextSource objects to search.

    Returns:
        ParsedTestFields with the first found values.

    Example:
        >>> sources = [
        ...     TextSource("FAIL_TO_PASS: test1", source_id="comment_123", priority=10),
        ...     TextSource("FAIL_TO_PASS: test2", source_id="issue_body", priority=0),
        ... ]
        >>> result = parse_test_fields_from_sources(sources)
        >>> result.fail_to_pass
        '["test1"]'
        >>> result.source_id
        'comment_123'
    """
    # Sort by priority (highest first)
    sorted_sources = sorted(sources, key=lambda s: s.priority, reverse=True)

    for source in sorted_sources:
        if not source.text:
            continue

        fail_to_pass = _extract_field(source.text, "FAIL_TO_PASS")
        pass_to_pass = _extract_field(source.text, "PASS_TO_PASS")

        # Only return if we found at least one field
        if fail_to_pass != "[]" or pass_to_pass != "[]":
            metadata = extract_metadata(source.text)
            return ParsedTestFields(
                fail_to_pass=fail_to_pass,
                pass_to_pass=pass_to_pass,
                metadata=metadata,
                source_id=source.source_id,
            )

    # No fields found in any source
    return ParsedTestFields(fail_to_pass="[]", pass_to_pass="[]")


def fetch_test_fields_from_issue(
    client: "GitHubAPIClient",
    owner: str,
    repo: str,
    issue_number: int,
) -> ParsedTestFields:
    """Fetch and parse test fields from a GitHub issue.

    Searches in order (first match wins):
    1. Issue comments (most recent first)
    2. Issue body

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        issue_number: Issue number.

    Returns:
        ParsedTestFields with found values.
    """
    sources: list[TextSource] = []

    # Fetch issue body
    try:
        issue_data = client.get(f"/repos/{owner}/{repo}/issues/{issue_number}")
        issue_body = issue_data.get("body", "") or ""
        if issue_body:
            sources.append(
                TextSource(
                    text=issue_body,
                    source_id="issue_body",
                    priority=0,
                )
            )
    except Exception as e:
        logger.warning(f"Failed to fetch issue body: {e}")

    # Fetch issue comments (most recent gets higher priority)
    try:
        comments = list(
            client.get_paginated(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")
        )
        # Reverse to check newest first
        for idx, comment in enumerate(reversed(comments)):
            comment_body = comment.get("body", "") or ""
            comment_id = str(comment.get("id", ""))
            if comment_body:
                sources.append(
                    TextSource(
                        text=comment_body,
                        source_id=comment_id,
                        priority=10 + idx,  # Higher priority for more recent comments
                    )
                )
    except Exception as e:
        logger.warning(f"Failed to fetch issue comments: {e}")

    return parse_test_fields_from_sources(sources)


def fetch_test_fields_from_commits(
    client: "GitHubAPIClient",
    owner: str,
    repo: str,
    commit_shas: list[str],
) -> ParsedTestFields:
    """Fetch and parse test fields from commit messages.

    Searches commit messages in order (most recent first).

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        commit_shas: List of commit SHAs to check.

    Returns:
        ParsedTestFields with found values.
    """
    sources: list[TextSource] = []

    # Check commits (most recent first based on list order, assuming sorted)
    for idx, commit_sha in enumerate(reversed(commit_shas)):
        try:
            commit_data = client.get(f"/repos/{owner}/{repo}/commits/{commit_sha}")
            message = commit_data.get("commit", {}).get("message", "") or ""
            if message:
                sources.append(
                    TextSource(
                        text=message,
                        source_id=f"commit_{commit_sha[:7]}",
                        priority=idx,
                    )
                )
        except Exception as e:
            logger.debug(f"Failed to fetch commit {commit_sha[:7]}: {e}")

    return parse_test_fields_from_sources(sources)


def fetch_test_fields_for_issue(
    client: "GitHubAPIClient",
    owner: str,
    repo: str,
    issue_number: int,
    commit_shas: list[str] | None = None,
) -> ParsedTestFields:
    """Fetch test fields from all available sources for an issue.

    Search order (first match wins):
    1. Issue comments (most recent first)
    2. Commit messages (if provided, most recent first)
    3. Issue body

    Args:
        client: GitHub API client.
        owner: Repository owner.
        repo: Repository name.
        issue_number: Issue number.
        commit_shas: Optional list of related commit SHAs.

    Returns:
        ParsedTestFields with found values.
    """
    # First try issue comments and body
    result = fetch_test_fields_from_issue(client, owner, repo, issue_number)
    if result.fail_to_pass != "[]" or result.pass_to_pass != "[]":
        return result

    # If not found and we have commits, try commit messages
    if commit_shas:
        result = fetch_test_fields_from_commits(client, owner, repo, commit_shas)
        if result.fail_to_pass != "[]" or result.pass_to_pass != "[]":
            return result

    # Nothing found
    return ParsedTestFields(fail_to_pass="[]", pass_to_pass="[]")
