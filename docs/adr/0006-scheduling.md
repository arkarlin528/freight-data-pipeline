# ADR-0006: Schedule with a cron container now; Lambda + EventBridge as the AWS-native option

- **Status:** Accepted
- **Date:** 2026-10-02

## Context
One run a day, a few seconds long, a few hundred rows. It must run unattended, log somewhere searchable, and make failures visible.

## Options considered
1. **Airflow / Dagster:** great for many interdependent jobs, but heavy to run for one daily job.
2. **A cron container (supercronic)** next to the other services on the existing EC2 host.
3. **AWS Lambda (container image) + EventBridge schedule:** no server, pay per run, and native CloudWatch logs and alarms.

## Decision
- **Default: supercronic** in the pipeline image (`deploy/crontab`, daily 22:00 UTC = 05:00 Bangkok, before quoting starts). It's container-friendly cron: logs to stdout, handles signals, and needs no root daemon. It deploys alongside projects #1 and #2 on the same host.
- **Ready alternative: `lambda_handler.handler`** for an EventBridge rule. Settings come from env vars and secrets from SSM; the raw zone goes to `/tmp` or S3.
- Logs are **JSON lines** (`--json-logs`), so either option is searchable in CloudWatch.
- CI also runs the pipeline daily against the mock site, so a parser broken by a dependency update is caught without a commit.

## Consequences
- ✅ No new infrastructure for the default, and a documented serverless path.
- ⚠️ cron gives no backfill or dependency graph. If more pipelines appear (e.g. port congestion, fuel surcharges), move to Dagster.
