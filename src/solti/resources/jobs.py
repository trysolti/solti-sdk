"""Jobs namespace: workload submission, polling and cancellation (api spec §3.2)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .._client import SoltiClient
from ..exceptions import TimeoutError, WorkloadFailedError
from . import Resource

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class Job(Resource):
    """A job API response. The create response's `job_id` is normalized to `.id`."""

    @property
    def id(self) -> str | None:
        """The job UUID — the create endpoint returns it as `job_id`."""
        return self.get("id") or self.get("job_id")

    def wait_until_complete(
        self,
        timeout_seconds: float | None = None,
        *,
        poll_interval_seconds: float = 10.0,
        cancel_on_timeout: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> Job:
        """Blocks until the job reaches a terminal state (10s default poll).

        Raises:
            WorkloadFailedError: The job ended in `failed`, or reported a
                non-zero `exit_code`.
            TimeoutError: `timeout_seconds` elapsed. If `cancel_on_timeout`
                is true, the job is cancelled before raising.
        """
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        last_status: str | None = None
        while True:
            current = self.client.jobs.get(self.get("name") or self.id)
            if on_progress is not None and current.get("status") != last_status:
                on_progress(current.get("status"))
                last_status = current.get("status")
            if current.get("status") in TERMINAL_STATUSES:
                _raise_if_failed(current)
                return current
            if deadline is not None and time.monotonic() >= deadline:
                if cancel_on_timeout:
                    self.client.jobs.cancel(self.id)
                raise TimeoutError(
                    f"Job '{current.get('name')}' did not complete within "
                    f"{timeout_seconds} seconds (last status: {current.get('status')})."
                )
            time.sleep(poll_interval_seconds)


def _raise_if_failed(job: Job) -> None:
    exit_code = job.get("exit_code")
    if job.get("status") == "failed" or (exit_code is not None and exit_code != 0):
        raise WorkloadFailedError(
            f"Workload '{job.get('name')}' failed"
            + (f" with exit code {exit_code}" if exit_code is not None else "")
            + ".",
            exit_code=exit_code,
            error_summary=job.get("error_summary"),
            oom=bool(job.get("oom_killed") or job.get("oom")),
        )


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
        volumes: dict[str, dict[str, Any]] | None = None,
        resources: dict[str, Any] | None = None,
        cloud: str | list[str] | None = None,
        region: str | list[str] | None = None,
        max_retries: int | None = None,
        labels: dict[str, str] | None = None,
        tags: list[str] | None = None,
    ) -> Job:
        """Submits a workload. Request payloads use camelCase wire keys
        (`namePrefix`, `maxRetries`, `mountPath`); the `gpu` shorthand
        (`"24Gi"` for `{"vram": "24Gi"}`) is passed through to the API.
        """
        payload: dict[str, Any] = {"image": image}
        if name is not None:
            payload["name"] = name
        if name_prefix is not None:
            payload["namePrefix"] = name_prefix
        if command is not None:
            payload["command"] = command
        if args is not None:
            payload["args"] = args
        if env is not None:
            payload["env"] = env
        if volumes is not None:
            payload["volumes"] = volumes
        if resources is not None:
            payload["resources"] = resources
        if cloud is not None:
            payload["cloud"] = cloud
        if region is not None:
            payload["region"] = region
        if max_retries is not None:
            payload["maxRetries"] = max_retries
        if labels is not None:
            payload["labels"] = labels
        if tags is not None:
            payload["tags"] = tags
        return Job(self._client, self._client.request("jobs", "POST", json_body=payload))

    def get(self, job_id_or_name: str) -> Job:
        """Fetches job state by UUID or unique name (UUID takes precedence)."""
        return Job(self._client, self._client.request(f"jobs/{job_id_or_name}", "GET"))

    def list(
        self,
        *,
        status: str | None = None,
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
        return _wrap(self._client, payload)

    def cancel(self, job_id_or_name: str) -> Job | None:
        """Cancels a running, booting, or queued job."""
        response = self._client.request(f"jobs/{job_id_or_name}/cancel", "POST")
        return Job(self._client, response) if isinstance(response, dict) else None


def _wrap(client: SoltiClient, payload: Any) -> list[Job]:
    from . import _wrap_list

    return _wrap_list(client, payload, "jobs", Job)
