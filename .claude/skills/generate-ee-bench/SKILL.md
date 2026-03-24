---
name: generate-ee-bench
description: Use when setting up .ee-bench/ configuration for a repository. Triggers when user asks to "generate ee-bench", "create ee-bench config", "set up evaluation", "bootstrap datapoint", or wants to prepare a repo for the EE-bench benchmark pipeline.
---

# Generate EE-Bench Configuration

**Announce at start:** "Using generate-ee-bench skill to set up evaluation configuration."

## Usage

The evaluation type is passed as a parameter:

```
/generate-ee-bench codegen
```

If no type is provided, show the available types and ask the user to pick one.

## Available Evaluation Types

| Type | Description | Reference |
|------|-------------|-----------|
| `codegen` | Code generation — Dockerfile, run.sh, parser.py, metadata.json | [codegen.md](references/codegen.md) |

## Workflow

1. Determine the evaluation type from the parameter or by asking the user
2. Read the corresponding reference file for that evaluation type
3. Follow the reference file instructions exactly — it contains the full detection logic, file specifications, and post-generation guidance