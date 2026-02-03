# ee_bench_dpaia

DPAIA (Data Patcher AI Agent) generator plugin for ee_bench_generator.

## Overview

This package provides generators that produce dataset records in the DPAIA format,
compatible with the SWE-bench evaluation framework for JVM-based projects.

## Generators

### dpaia_jvm

Generates dataset records with the following schema:

- `instance_id`: Unique identifier (format: `owner__repo__number`)
- `repo`: Repository clone URL
- `base_commit`: Commit SHA to checkout before applying patch
- `patch`: The diff that fixes the issue
- `problem_statement`: Issue/PR description
- `hints_text`: Optional hints for solving the problem
- `FAIL_TO_PASS`: JSON array of tests that should fail then pass
- `PASS_TO_PASS`: JSON array of tests that should always pass
- `created_at`: ISO8601 timestamp

## Usage

```bash
ee-dataset generate --provider github_pull_requests --generator dpaia_jvm \
    --selection '{"resource": "pull_requests", "filters": {"repo": "owner/repo", "pr_numbers": [42]}}'
```
