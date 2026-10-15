"""wait_until_complete polling: success, failure, and timeout+cancel paths."""

from __future__ import annotations

import pytest

import solti._client as client_module
from conftest import json_response
from solti import SoltiClient, exceptions


def job_response(**overrides: object) -> dict:
    base = {"id": "j1", "name": "train-run-x7k9", "status": "running",
            "vm_status": "assigned", "exit_code": None, "error_summary": None}
    return {**base, **overrides}


def always_running(_request):
    return json_response(payload=job_response())


class TestWaitUntilComplete:
    def test_success_polling_returns_final_job(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        states = iter([
            job_response(status="queued", vm_status="nonassigned"),
            job_response(status="running"),
            job_response(status="succeeded", exit_code=0, actual_cost=1.23),
        ])

        def responder(request):
            # The create POST consumes its own response, not a poll state.
            if request.method == "POST":
                return json_response(payload=job_response(status="queued", vm_status="nonassigned"))
            return json_response(payload=next(states))

        mock_api.respond_with(responder)

        job = client.jobs.create(image="alpine:latest")
        seen: list[str | None] = []
        final = job.wait_until_complete(poll_interval_seconds=0.01, on_progress=seen.append)

        assert final.status == "succeeded"
        assert final.actual_cost == 1.23
        assert seen == ["queued", "running", "succeeded"]
        assert len(mock_api.calls(method="GET", path="/1/jobs/train-run-x7k9")) == 3

    def test_non_zero_exit_code_raises_workload_failed(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        states = iter([
            job_response(status="running"),
            job_response(status="failed", exit_code=3,
                         error_summary="Traceback: process crashed", oom_killed=False),
        ])
        mock_api.respond_with(lambda req: json_response(payload=next(states)))

        job = client.jobs.get("j1")
        with pytest.raises(exceptions.WorkloadFailedError) as excinfo:
            job.wait_until_complete(poll_interval_seconds=0.01)
        assert excinfo.value.exit_code == 3
        assert excinfo.value.error_summary == "Traceback: process crashed"
        assert excinfo.value.oom is False

    def test_oom_flag_is_surfaced(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        mock_api.respond_with(
            lambda req: json_response(payload=job_response(status="failed", exit_code=137,
                                                           oom_killed=True,
                                                           error_summary="OOMKilled"))
        )
        job = client.jobs.get("j1")
        with pytest.raises(exceptions.WorkloadFailedError) as excinfo:
            job.wait_until_complete(poll_interval_seconds=0.01)
        assert excinfo.value.oom is True
        assert excinfo.value.exit_code == 137

    def test_cancelled_is_terminal_and_does_not_raise(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        mock_api.respond_with(lambda req: json_response(payload=job_response(status="cancelled")))
        final = client.jobs.get("j1").wait_until_complete(poll_interval_seconds=0.01)
        assert final.status == "cancelled"

    def test_timeout_raises_and_cancels_when_asked(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        mock_api.respond_with(always_running)

        job = client.jobs.get("j1")
        with pytest.raises(exceptions.TimeoutError):
            job.wait_until_complete(timeout_seconds=0.05, poll_interval_seconds=0.01,
                                    cancel_on_timeout=True)

        # Built-in TimeoutError catches it too (dual inheritance).
        with pytest.raises(TimeoutError):
            client.jobs.get("j1").wait_until_complete(timeout_seconds=0.05,
                                                      poll_interval_seconds=0.01,
                                                      cancel_on_timeout=True)

        cancels = mock_api.calls(method="POST", path="/1/jobs/j1/cancel")
        assert len(cancels) == 2  # both waits cancelled on timeout

    def test_timeout_without_cancel_does_not_cancel(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        mock_api.respond_with(always_running)

        job = client.jobs.get("j1")
        with pytest.raises(exceptions.TimeoutError):
            job.wait_until_complete(timeout_seconds=0.05, poll_interval_seconds=0.01)

        assert mock_api.calls(method="POST", path="/1/jobs/j1/cancel") == []
