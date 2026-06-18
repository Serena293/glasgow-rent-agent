# Render Deploy

This project is configured for Render with:

- one Cron Job: `glasgow-rent-agent`
- one free Render Postgres database: `glasgow-rent-agent-db`
- one secret env var: `GOOGLE_TOKEN_JSON`

The cron schedule is:

```text
30 7,17 * * *
```

Render cron schedules are UTC. This means the job runs around morning and evening UK time, with a one-hour shift around daylight saving time.

The database uses Render's free Postgres plan, which is limited to 30 days. That is intentional for this short house search.

## Before Deploy

Make sure the local Gmail test has worked once:

```powershell
house-agent email-test
```

This creates:

```text
.secrets/gmail_token.json
```

Copy the entire contents of that file. In PowerShell:

```powershell
Get-Content .secrets\gmail_token.json -Raw
```

You will paste that JSON into Render as the `GOOGLE_TOKEN_JSON` secret.

## Deploy

1. Push this project to GitHub.
2. In Render, create a new Blueprint from the repo.
3. Render will read `render.yaml`.
4. When prompted for `GOOGLE_TOKEN_JSON`, paste the full JSON from `.secrets\gmail_token.json`.
5. Let Render create the Cron Job and Postgres database.

## First Run Safety

`HOUSE_AGENT_BASELINE_ON_EMPTY_DB=true` is set on Render.

That means the first run on an empty Render database creates a baseline and sends no email. After that, emails include only new listings or price drops.

## Manual Test On Render

Open the `glasgow-rent-agent` Cron Job in Render and click `Trigger Run`.

Expected first-run log:

```text
Database is empty. Creating first-run baseline without sending email.
First-run baseline complete.
```

Expected later logs:

```text
Scheduled mode selected: morning
Checking openrent...
...
```
