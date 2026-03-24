"""GitHub API client with rate-limit-aware retries for export v2 scripts.

Shared module used by resolve_instances_v2.py. Not run directly.

Requires:
    - GH_TOKEN env var set
    - gh CLI installed

Rate limit handling:
    All API calls detect 403/429 responses, read Retry-After or x-ratelimit-reset
    headers, wait the exact duration, then retry (up to 3 times).
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional


def _get_token() -> str:
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("Error: GH_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)
    return token


def _run_gh(args: list[str], *, max_retries: int = 3) -> subprocess.CompletedProcess:
    """Run a gh CLI command with rate-limit-aware retries."""
    for attempt in range(max_retries + 1):
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            env={**os.environ, "GH_TOKEN": _get_token()},
        )
        if result.returncode == 0:
            return result

        # Check for rate limit indicators in stderr
        stderr = result.stderr.lower()
        if "rate limit" in stderr or "retry-after" in stderr or "403" in stderr or "429" in stderr:
            if attempt < max_retries:
                wait = _parse_retry_wait(result.stderr)
                print(f"Rate limited. Waiting {wait}s before retry {attempt + 1}/{max_retries}...", file=sys.stderr)
                time.sleep(wait)
                continue

        # Non-rate-limit error or retries exhausted
        if attempt == max_retries or ("rate limit" not in stderr and "429" not in stderr):
            print(f"gh command failed: {result.stderr}", file=sys.stderr)
            result.check_returncode()

    return result


def _parse_retry_wait(stderr: str) -> float:
    """Extract wait time from error output. Falls back to 60s."""
    import re

    # Try Retry-After header value
    match = re.search(r"retry-after[:\s]+(\d+)", stderr, re.IGNORECASE)
    if match:
        return float(match.group(1))

    # Try x-ratelimit-reset timestamp
    match = re.search(r"x-ratelimit-reset[:\s]+(\d+)", stderr, re.IGNORECASE)
    if match:
        reset_time = float(match.group(1))
        wait = reset_time - time.time()
        if wait > 0:
            return min(wait + 1, 300)  # Cap at 5 minutes

    return 60.0


@dataclass
class BoardItem:
    """A project board item with its Data field URL."""
    node_id: str
    repo_name: str
    number: int
    data_url: Optional[str] = None


def search_board_items(org: str, project_number: int, query: str) -> list[dict]:
    """Search project board items via GitHub Search API.

    Returns list of dicts with keys: node_id, repository_url, number.
    """
    items = []
    page = 1
    per_page = 100

    while True:
        result = _run_gh([
            "api", "-X", "GET", "search/issues",
            "-H", "X-GitHub-Api-Version: 2022-11-28",
            "-f", f"q=project:{org}/{project_number} is:pr {query}",
            "-f", f"per_page={per_page}",
            "-f", f"page={page}",
        ])

        data = json.loads(result.stdout)
        for item in data.get("items", []):
            items.append({
                "node_id": item["node_id"],
                "repo_name": item["repository_url"].rsplit("/", 1)[-1],
                "number": item["number"],
            })

        if len(data.get("items", [])) < per_page:
            break
        page += 1

    return items


def fetch_data_field_urls(org: str, project_number: int, node_ids: list[str]) -> dict[str, str]:
    """Batch-fetch Data field values for project items via GraphQL.

    Returns dict mapping node_id -> Data field URL.
    """
    if not node_ids:
        return {}

    # First get the project ID and Data field ID
    project_info = _run_gh([
        "api", "graphql",
        "-f", f"query=query($org:String!, $number:Int!) {{ organization(login: $org) {{ projectV2(number: $number) {{ id fields(first: 50) {{ nodes {{ ... on ProjectV2FieldCommon {{ id name }} }} }} }} }} }}",
        "-f", f"org={org}",
        "-F", f"number={project_number}",
    ])

    proj_data = json.loads(project_info.stdout)
    project_node = proj_data["data"]["organization"]["projectV2"]
    project_id = project_node["id"]

    data_field_id = None
    for field in project_node["fields"]["nodes"]:
        if field.get("name") == "Data":
            data_field_id = field["id"]
            break

    if not data_field_id:
        print("Warning: 'Data' field not found in project", file=sys.stderr)
        return {}

    # Fetch project items with Data field values in batches
    result_map: dict[str, str] = {}
    cursor = None

    while True:
        after_clause = f', after: "{cursor}"' if cursor else ""
        query = f"""query($projectId: ID!) {{
          node(id: $projectId) {{
            ... on ProjectV2 {{
              items(first: 100{after_clause}) {{
                pageInfo {{ hasNextPage endCursor }}
                nodes {{
                  content {{
                    ... on PullRequest {{ id }}
                    ... on Issue {{ id }}
                  }}
                  fieldValues(first: 20) {{
                    nodes {{
                      ... on ProjectV2ItemFieldTextValue {{
                        field {{ ... on ProjectV2FieldCommon {{ id }} }}
                        text
                      }}
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}"""

        resp = _run_gh([
            "api", "graphql",
            "-f", f"query={query}",
            "-f", f"projectId={project_id}",
        ])

        resp_data = json.loads(resp.stdout)
        items_data = resp_data["data"]["node"]["items"]

        for item in items_data["nodes"]:
            content = item.get("content")
            if not content or "id" not in content:
                continue

            content_id = content["id"]
            if content_id not in node_ids:
                continue

            for fv in item.get("fieldValues", {}).get("nodes", []):
                field = fv.get("field", {})
                if field.get("id") == data_field_id and fv.get("text"):
                    result_map[content_id] = fv["text"]

        page_info = items_data["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    return result_map


def parse_data_url(url: str) -> Optional[dict]:
    """Parse a GitHub blob URL into components.

    Example: https://github.com/dpaia/dataset/blob/main/codegen/efcore/dotnet__efcore-31808.json
    Returns: {owner, repo, branch, path, instance_id}
    """
    if not url or "github.com" not in url or "/blob/" not in url:
        return None

    # Strip https://github.com/
    path = url.split("github.com/", 1)[-1]
    parts = path.split("/")
    if len(parts) < 5:
        return None

    owner = parts[0]
    repo = parts[1]
    # parts[2] == "blob"
    branch = parts[3]
    file_path = "/".join(parts[4:])

    # Instance ID: strip .json extension from filename, derive directory path
    if file_path.endswith(".json"):
        instance_id = file_path.rsplit("/", 1)[-1].replace(".json", "")
        dir_path = file_path.replace(".json", "")
    else:
        instance_id = file_path.rsplit("/", 1)[-1]
        dir_path = file_path

    return {
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "file_path": file_path,
        "dir_path": dir_path,
        "instance_id": instance_id,
    }


def download_content(owner: str, repo: str, branch: str, file_path: str) -> Optional[str]:
    """Download file content from GitHub API. Returns content string or None."""
    try:
        result = _run_gh([
            "api", f"repos/{owner}/{repo}/contents/{file_path}",
            "-q", ".content",
            "-H", f"ref: {branch}",
        ])
        import base64
        return base64.b64decode(result.stdout.strip()).decode("utf-8")
    except (subprocess.CalledProcessError, Exception) as e:
        print(f"Warning: failed to download {owner}/{repo}/{file_path}: {e}", file=sys.stderr)
        return None