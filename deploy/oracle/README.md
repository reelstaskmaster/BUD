# BUD on Oracle Cloud Always Free

This deployment target is designed for an OCI Ampere A1 Always Free VM. Oracle currently documents 1,500 OCPU-hours and 9,000 GB-hours per month for A1 Always Free, equivalent to 2 OCPUs and 12 GB RAM for an Always Free tenancy. Keep the VM within those limits.

## Target

- Ubuntu Linux ARM64
- Docker Engine + Docker Compose
- BUD/Hermes
- PostgreSQL + pgvector
- No Railway dependency
- Secrets stored only in `deploy/oracle/.env`

## First boot

1. Create an OCI Always Free Ampere A1 VM in the tenancy's home region.
2. Use Ubuntu ARM64.
3. Allocate at most 2 OCPUs and 12 GB RAM total across A1 instances.
4. Connect over SSH.
5. Install Docker Engine and the Docker Compose plugin.
6. Clone this repository to `/opt/bud`.
7. Copy `deploy/oracle/.env.example` to `deploy/oracle/.env`.
8. Set a strong random `POSTGRES_PASSWORD` and the Telegram/provider secrets.
9. Run:
   `docker compose --env-file deploy/oracle/.env -f deploy/oracle/docker-compose.yml up -d --build`

## Security

- Do not expose PostgreSQL port 5432 to the Internet.
- OCI security rules should allow SSH only from your administration IP where practical.
- Telegram bot traffic is outbound; no public HTTP port is required for the basic polling setup.
- Keep MCP server configuration empty until each server has been security-audited and explicitly approved.
- Do not commit `.env` or provider/API tokens.
- Keep automatic OS security updates enabled.
- Back up the PostgreSQL volume before major changes.

## Operations

Status:
`docker compose --env-file deploy/oracle/.env -f deploy/oracle/docker-compose.yml ps`

Logs:
`docker compose --env-file deploy/oracle/.env -f deploy/oracle/docker-compose.yml logs -f bot`

Restart:
`docker compose --env-file deploy/oracle/.env -f deploy/oracle/docker-compose.yml restart`

Update:
`git pull --ff-only origin main`
then rebuild with the same compose command.

## Oracle caveat

Oracle documents that Always Free compute must be created in the home region. It also notes that Always Free instances can be reclaimed if they remain below its idle thresholds for a 7-day period. Keep BUD active and monitor the instance.
