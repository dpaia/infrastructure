# Get Latest Commit Action

This GitHub Action fetches the latest commit related to a GitHub issue. It tries multiple methods to find the most relevant commit:

1. First, it looks for commits directly linked to the issue
2. If none found, it checks for related pull requests and their commits
3. As a fallback, it uses the latest repository commit

The action also retrieves the parent commit (base commit) of the found commit.

## Inputs

| Input | Description | Required |
|-------|-------------|----------|
| `organization` | GitHub organization name | Yes |
| `repository` | Repository name | Yes |
| `issue_id` | Issue number | Yes |
| `github_token` | GitHub token for API access | Yes |

## Outputs

| Output | Description |
|--------|-------------|
| `commit_hash` | The hash of the latest commit related to the issue |
| `base_commit_hash` | The hash of the parent commit (base commit) |

## Example Usage

```yaml
jobs:
  get-commit:
    runs-on: ubuntu-latest
    outputs:
      commit_hash: ${{ steps.get-commit.outputs.commit_hash }}
      base_commit_hash: ${{ steps.get-commit.outputs.base_commit_hash }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        
      - name: Get latest commit
        id: get-commit
        uses: ./.github/actions/get-latest-commit
        with:
          organization: ${{ github.event.inputs.organization }}
          repository: ${{ github.event.inputs.repository }}
          issue_id: ${{ github.event.inputs.issue_id }}
          github_token: ${{ secrets.GITHUB_TOKEN }}

  use-commit:
    needs: get-commit
    runs-on: ubuntu-latest
    steps:
      - name: Use commit hash
        run: |
          echo "Latest commit: ${{ needs.get-commit.outputs.commit_hash }}"
          echo "Base commit: ${{ needs.get-commit.outputs.base_commit_hash }}"
```

## How It Works

The action uses GitHub's API to find commits related to an issue:

1. It first checks the issue timeline for directly referenced commits
2. If no commits are found, it looks for cross-referenced pull requests and their commits
3. As a last resort, it uses the latest commit in the repository

For the base commit, it retrieves the parent of the found commit or falls back to an older repository commit if no parent is found.