# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security vulnerability.

Report privately to the repository maintainers with:
- a short description of the issue;
- affected component or file;
- reproduction steps;
- potential impact.

Do not include secrets or personal data unless necessary.

## Scope

Security-sensitive areas include:
- API and bot credentials;
- autonomous agent tools and permissions;
- production configuration and deployments;
- external integrations and webhooks.

## Development rules

- Never commit secrets, tokens, or private credentials.
- Autonomous actions must use the minimum required permissions.
- Destructive or production-changing actions require explicit authorization.
- Security fixes should be tested before deployment.

## Supported versions

The default branch is the active development version.
