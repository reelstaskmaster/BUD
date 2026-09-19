# BUD Two-Agent Development Loop

BUD uses two logical roles.

## Developer
Owns implementation and architecture. It reads the repository, plans the change, edits code, runs checks, and prepares a reviewable change.

## Reviewer
Acts independently as QA and security reviewer. It examines the diff, tests, configuration, migrations, failure handling, and regression risk.

## State machine

TODO -> IMPLEMENTING -> TESTING -> REVIEW -> CHANGES_REQUESTED -> TESTING -> REVIEW -> APPROVED

A deployment is allowed only from APPROVED.

## Initial backlog
1. Establish a reproducible local test command.
2. Audit startup/configuration and dependency management.
3. Add automated tests around the Telegram message pipeline.
4. Add health/error observability.
5. Formalize database migration checks.
6. Add agent task/review records.
7. Add deployment gates.

This document describes the workflow; it does not itself create autonomous background execution.
