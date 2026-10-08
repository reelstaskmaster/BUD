---
name: plan
description: "Plan complex implementation work before execution and define concrete verification criteria."
version: 1.0.0
author: Nous Research / Hermes Registry
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, workflow, software-development]
---

# Plan

## When to use

Use for implementation, refactoring, deployment, debugging, security review, or other multi-step tasks.

## Procedure

1. State the requested outcome.
2. Identify the smallest sequence of actions that can achieve it.
3. Separate read-only inspection from write actions.
4. Define what evidence will prove each important step succeeded.
5. Execute only after the plan is internally consistent.
6. Re-check external state before reporting completion.

## Safety

Do not turn a plan into permission to perform unrelated destructive actions. Do not claim a step happened without evidence.
