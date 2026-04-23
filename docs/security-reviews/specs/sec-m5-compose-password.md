# SEC-M5: Parameterize Postgres credentials in `docker-compose.yml`

## User Story

As a **platform operator**, I want `docker-compose.yml` to fail fast when
the Postgres password isn't set via env, so that the compose file cannot
accidentally boot a production database with the string `stronghold` as
the password.

## Background

`docker-compose.yml:40–42` hardcodes
`POSTGRES_USER=stronghold / POSTGRES_PASSWORD=stronghold`, ignoring the
`.env` file the header comment tells operators to edit. Docker Compose
does not require env vars to be defined unless you use the `:?err`
syntax.

## Acceptance Criteria

- AC1: Given `.env` does not set `POSTGRES_PASSWORD`, When `docker compose up` runs, Then compose exits with a clear error (uses `${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}`).
- AC2: Given `.env` sets `POSTGRES_PASSWORD=<anything>`, When `docker compose up` runs, Then both the `postgres` container and the `stronghold` service's `DATABASE_URL` use the same value.
- AC3: Given the `.env.example`, When read, Then it lists `POSTGRES_PASSWORD=change-me` under a "REQUIRED" section.
- AC4: Given any documentation referencing compose bootstrap, When updated, Then the instructions mention setting `POSTGRES_PASSWORD` before `compose up`.

## Test Mapping

| AC  | Test path                                 | Test function                             | Tier     |
|-----|-------------------------------------------|-------------------------------------------|----------|
| AC1 | tests/deploy/test_compose.py              | test_compose_fails_without_pg_password    | critical |
| AC2 | tests/deploy/test_compose.py              | test_compose_env_propagates_to_services   | happy    |
| AC3 | tests/deploy/test_compose.py              | test_env_example_documents_required_vars  | happy    |
| AC4 | (manual doc review)                       | —                                         | —        |

## Files to Touch

- Modify: `docker-compose.yml` — `${POSTGRES_PASSWORD:?…}` in both the postgres `environment:` and the stronghold `DATABASE_URL`; same treatment for `POSTGRES_USER` and `POSTGRES_DB`.
- Modify: `.env.example` — add REQUIRED section with `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`.
- Modify: `README.md` / install docs — update bootstrap steps.
- New: `tests/deploy/test_compose.py` — invokes `docker compose config` with and without the env set.

## Rollback

Revert the compose file if the fail-fast behavior breaks someone's
scripted bootstrap. Low risk since the change is cosmetic for correctly
configured deployments.
