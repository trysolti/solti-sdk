# Solti Python SDK

Python SDK for the [Solti Platform](https://solti.run) — schedule and run asynchronous workloads without managing infrastructure.

**Package:** `solti-sdk` (PyPI) · **Import:** `solti` · **License:** UNLICENSED (private, mirrors `@solti/cli`)

## Installation

```bash
uv add solti-sdk
# or
pip install solti-sdk
```

## Quickstart

```python
from solti import SoltiClient
from solti.exceptions import WorkloadFailedError, TimeoutError

# api_key falls back to the SOLTI_API_KEY environment variable.
# Project selection uses the X-Solti-Project-Id header (project_id arg or SOLTI_PROJECT_ID env).
client = SoltiClient(api_key="eyJhbGciOi...", api_url="https://api.solti.run/1", project_id="proj-...")

# 1. Define and submit the workload
job = client.jobs.create(
    name="pytorch-train-epoch-50",       # or name_prefix="train-epoch-"
    image="pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime",
    command=["python3"],
    args=["train.py", "--epochs", "50"],
    env={"TORCH_OMP_NUM_THREADS": "8"},
    volumes={                            # map keyed by volume name
        "datasets": {
            "bucket": "ml-training-artifacts",
            "mountPath": "/mnt/s3",
            "connection": "my-aws-s3",   # optional
            "prefix": "checkpoints",     # optional
        }
    },
    resources={"cpu": 8, "memory": "32Gi", "gpu": "24Gi"},  # gpu shorthand for {"vram": "24Gi"}
    cloud=["aws", "gcp"],
    region="americas",
    max_retries=3,
    labels={"environment": "production", "team": "ml"},
    tags=["pytorch", "training"],
)

print(f"Submitted Job: {job.name} ({job.id}) — {job.status}")

try:
    # 2. Block and poll progress (default poll interval 10s)
    final_job = job.wait_until_complete(timeout_seconds=7200)
    print(f"Succeeded! Actual cost: ${final_job.actual_cost}")
except WorkloadFailedError as e:
    print(f"Workload failed with exit code {e.exit_code}\n{e.error_summary}")
except TimeoutError:
    client.jobs.cancel(job.id)
```

## Connections, Cronjobs & Keys

```python
client.connections.list()
client.connections.get("my-aws-s3")
client.connections.create(name="new-s3", type="aws", credentials={
    "access_key_id": "AKIA...", "secret_access_key": "wJal...", "region": "us-east-1",
})
client.connections.delete("old-connection")

cron = client.cronjobs.create(
    name="nightly-backup",
    cron_spec="0 2 * * *",               # UTC
    job_definition={"image": "alpine:latest", "command": ["echo", "backup complete"]},
)
client.cronjobs.get(cron.id)             # or client.cronjobs.get("nightly-backup")
client.cronjobs.patch("nightly-backup", is_active=False)
client.cronjobs.delete("nightly-backup")

client.keys.list()
client.keys.create(name="ci", role="editor")
client.keys.delete("ci")
```

## Error handling

HTTP errors map to typed exceptions (`solti.exceptions`), per `constitution/tools/sdk.md` §5:

| Exception | HTTP | Notes |
| :--- | :--- | :--- |
| `AuthenticationError` | 401 | Invalid or expired API key (Zitadel PAT). |
| `PermissionDeniedError` | 403 | Key role lacks access (e.g. `viewer` on a write). |
| `NotFoundError` | 404 | Unknown job / connection / cronjob / key. |
| `ConflictError` | 409 | Duplicate resource name. |
| `ValidationError` | 422 | Malformed payload (invalid cron expression, bad volume, …). |
| `RateLimitError` | 429 | Exposes `retry_after` (seconds) and the `X-RateLimit-*` headers. |
| `WorkloadFailedError` | — | Raised by `wait_until_complete`; carries `exit_code`, `error_summary`, `oom`. |
| `TimeoutError` | — | Client-side wait timeout in `wait_until_complete` (also a `builtin.TimeoutError`). |

All exceptions derive from `SoltiError`, which exposes `status`, `payload` and `headers`.

**Rate-limit retry policy** (mirrors `solti-cli/src/api/client.ts`): idempotent reads (`GET`)
auto-retry up to 2 times honoring the `Retry-After` header (default 5s, capped at 30s).
Mutations surface `RateLimitError` to the caller immediately.

## Host strategy

Per-project wildcard hosts (`<project-id>.api.solti.run`) are **not deployed**. The SDK targets
the global host (`https://api.solti.run/1`, preview: `https://preview.api.solti.run/1`) and
selects the project via the `X-Solti-Project-Id` header — the same mechanism as the Solti CLI.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv build
```
