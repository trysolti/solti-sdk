"""Jobs namespace: workload submission, polling and cancellation (api spec §3.2)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, PrivateAttr

from .._client import SoltiClient
from ..exceptions import TimeoutError, WorkloadFailedError
from ..types import (
    CreateJobRequest,
    VmStatus,
    WorkloadStatus,
)

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"succeeded", "failed", "cancelled"}
)


class Job(BaseModel):
    """A job API response (snake_case fields). The create response's `job_id`
    is normalized to `.id`."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    #: Client handle backing `wait_until_complete`; not serialized.
    _client: SoltiClient | None = PrivateAttr(default=None)

    id: str | None = Field(None, validation_alias=AliasChoices("id", "job_id"))
    name: str | None = None
    status: WorkloadStatus | None = None
    image: str | None = None
    vm_status: VmStatus | None = None
    estimated_cost: float | None = None
    actual_cost: float | None = None
    retry_count: int | None = None
    max_retries: int | None = None
    error_summary: str | None = None
    exit_code: int | None = None
    oom: bool | None = None
    #: OOM flag (alternate wire key for the same signal).
    oom_killed: bool | None = None
    labels: dict[str, str] | None = None
    tags: list[str] | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def wait_until_complete(
        self,
        timeout_seconds: float | None = None,
        *,
        poll_interval_seconds: float = 10.0,
        cancel_on_timeout: bool = False,
        on_progress: Callable[[WorkloadStatus], None] | None = None,
    ) -> Job:
        """Blocks until the job reaches a terminal state (10s default poll).

        Raises:
            WorkloadFailedError: The job ended in `failed`, or reported a
                non-zero `exit_code`.
            TimeoutError: `timeout_seconds` elapsed. If `cancel_on_timeout`
                is true, the job is cancelled before raising.
        """
        if self._client is None:
            raise RuntimeError(
                "Job is not bound to a client; obtain jobs via SoltiClient.jobs."
            )
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        last_status: WorkloadStatus | None = None
        while True:
            current = self._client.jobs.get(self.name or self.id or "")
            if on_progress is not None and current.status != last_status:
                on_progress(current.status)
                last_status = current.status
            if current.status in TERMINAL_STATUSES:
                _raise_if_failed(current)
                return current
            if deadline is not None and time.monotonic() >= deadline:
                if cancel_on_timeout:
                    self._client.jobs.cancel(self.id or "")
                raise TimeoutError(
                    f"Job '{current.name}' did not complete within "
                    f"{timeout_seconds} seconds (last status: {current.status})."
                )
            time.sleep(poll_interval_seconds)


def _raise_if_failed(job: Job) -> None:
    if job.status == "failed" or (job.exit_code is not None and job.exit_code != 0):
        raise WorkloadFailedError(
            f"Workload '{job.name}' failed"
            + (f" with exit code {job.exit_code}" if job.exit_code is not None else "")
            + ".",
            exit_code=job.exit_code,
            error_summary=job.error_summary,
            oom=bool(job.oom or job.oom_killed),
        )


def _to_job(client: SoltiClient, data: Any) -> Job:
    """Validates an API payload into a `Job` bound to `client`."""
    job = Job.model_validate(data)
    job._client = client
    return job


class JobsResource:
    """`/1/jobs` — submit and manage asynchronous workloads."""

    def __init__(self, client: SoltiClient) -> None:
        self._client = client

    def create(
        self,
        *,
        image: str,
        command: list[str] | None = None,
        args: list[str] | None = None,
        name: str | None = None,
        name_prefix: str | None = None,
        env: dict[str, str] | None = None,
        volumes: dict[str, Any] | None = None,
        resources: dict[str, Any] | None = None,
        cloud: Any | None = None,
        region: str | list[str] | None = None,
        max_retries: int | None = None,
        labels: dict[str, str] | None = None,
        tags: list[str] | None = None,
    ) -> Job:
        """Submits a workload. Keyword arguments validate into
        `CreateJobRequest`; request payloads use camelCase wire keys
        (`namePrefix`, `maxRetries`, `mountPath`); the `gpu` shorthand
        (`"24Gi"` for `{"vram": "24Gi"}`) is passed through to the API.
        """
        request = CreateJobRequest(
            image=image,
            command=command,
            args=args,
            name=name,
            name_prefix=name_prefix,
            env=env,
            volumes=volumes,
            resources=resources,
            cloud=cloud,
            region=region,
            max_retries=max_retries,
            labels=labels,
            tags=tags,
        )
        payload = request.model_dump(by_alias=True, exclude_none=True)
        return _to_job(self._client, self._client.request("jobs", "POST", json_body=payload))

    def get(self, job_id_or_name: str) -> Job:
        """Fetches job state by UUID or unique name (UUID takes precedence)."""
        return _to_job(self._client, self._client.request(f"jobs/{job_id_or_name}", "GET"))

    def list(
        self,
        *,
        status: WorkloadStatus | None = None,
        tag: str | None = None,
        label: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Job]:
        """Lists jobs. `label` filters use the `key:value` form; pagination
        uses `limit`/`offset` (default page 50, max 200).
        """
        payload = self._client.request(
            "jobs",
            "GET",
            params={"status": status, "tag": tag, "label": label, "limit": limit, "offset": offset},
        )
        items = payload.get("jobs") if isinstance(payload, dict) else payload
        return [_to_job(self._client, item) for item in (items or [])]

    def cancel(self, job_id_or_name: str) -> Job | None:
        """Cancels a running, booting, or queued job."""
        response = self._client.request(f"jobs/{job_id_or_name}/cancel", "POST")
        return _to_job(self._client, response) if isinstance(response, dict) else None
