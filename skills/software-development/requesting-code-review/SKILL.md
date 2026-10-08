---
name: requesting-code-review
description: "Perform a pre-release review focused on correctness, security, regressions, tests, and deployment readiness."
version: 1.0.0
author: Nous Research / Hermes Registry
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, security, release]
---

# Release Code Review

## When to use

Use before shipping a production change, merging a feature, or declaring the agent release-ready.

## Review order

1. Check the diff and affected execution paths.
2. Check secrets, credentials, shell execution, network access, deserialization, and path handling.
3. Check dependency and configuration changes.
4. Check tests and failure handling.
5. Check deployment configuration and health checks.
6. Verify that claims in the release report match observed evidence.

## Release gate

Block release when there is an unresolved critical security issue, a broken required test, a missing runtime dependency, or an unverified deployment assumption.
