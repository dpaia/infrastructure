---
name: verify-ee-bench
description: Use when verifying .ee-bench/ configuration works correctly. Triggers when user asks to "verify ee-bench", "test ee-bench config", "validate datapoint", or after generate-ee-bench completes. Builds Docker image and runs tests to validate the configuration.
---

# Verify EE-Bench Configuration

**Announce at start:** "Using verify-ee-bench skill to validate the .ee-bench configuration."

## Usage

The evaluation type is passed as a parameter:

```
/verify-ee-bench codegen
```

If no type is provided, detect from the `.ee-bench/` directory structure (look for `codegen/` subdirectory).

## Available Evaluation Types

| Type | Description | Reference |
|------|-------------|-----------|
| `codegen` | Verify codegen config — build Docker image, discover tests, run evaluation | [codegen.md](references/codegen.md) |

## Workflow

1. Determine the evaluation type from the parameter or by detecting `.ee-bench/` subdirectories
2. Read the corresponding reference file for that evaluation type
3. Follow the reference file instructions exactly — it contains the full verification procedure
4. Report results to the user with pass/fail verdict

## Prerequisites

- Docker must be running on the host machine
- The current directory must contain `.ee-bench/codegen/` (or the relevant eval type directory)
- The current directory must be a git repository