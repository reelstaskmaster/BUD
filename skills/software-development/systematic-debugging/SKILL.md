---
name: systematic-debugging
description: "Find the root cause before changing code; verify the fix against the original failure."
version: 1.0.0
author: Nous Research / Hermes Registry
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, root-cause, verification]
---

# Systematic Debugging

## When to use

Use when a task reports a bug, failed deployment, broken integration, unexpected behavior, or regression.

## Procedure

1. Reproduce or inspect the failure using available evidence.
2. Locate the first meaningful failure, not merely the last error.
3. Form a specific root-cause hypothesis.
4. Inspect the relevant configuration, dependency, and call path.
5. Make the smallest safe correction.
6. Re-run the failing check.
7. Check for regressions and report the evidence.

## Safety

Do not repeatedly guess-and-change without evidence. Preserve unrelated behavior and avoid destructive cleanup while the dependency graph is uncertain.
