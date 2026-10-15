"""Error-mapping and 429 rate-limit retry behavior (CLI semantics, generalized)."""

from __future__ import annotations

import pytest

import solti._client as client_module
from conftest import json_response
from solti import SoltiClient, exceptions


class TestRateLimitRetry:
    def test_get_429_then_success_retries_honoring_retry_after(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(client_module.time, "sleep", lambda s: sleeps.append(s))
        state = {"count": 0}

        def responder(request):
            state["count"] += 1
            if state["count"] == 1:
                return json_response(
                    status=429,
                    payload={"code": "rate_limit_exceeded",
                             "message": "Rate limit exceeded for this project."},
                    headers={"Retry-After": "0.01", "X-RateLimit-Limit": "120",
                             "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1728123456"},
                )
            return json_response(payload={"jobs": []})

        mock_api.respond_with(responder)
        jobs = client.jobs.list()
        assert jobs == []
        gets = mock_api.calls(method="GET", path="/1/jobs")
        assert len(gets) == 2
        assert sleeps == [0.01]  # honored Retry-After

    def test_retry_after_capped_at_30s(self, mock_api, client: SoltiClient,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(client_module.time, "sleep", lambda s: sleeps.append(s))
        state = {"count": 0}

        def responder(request):
            state["count"] += 1
            if state["count"] == 1:
                return json_response(status=429, headers={"Retry-After": "120"})
            return json_response(payload={"jobs": []})

        mock_api.respond_with(responder)
        client.jobs.list()
        assert sleeps == [30.0]  # capped

    def test_missing_retry_after_defaults_to_5s(self, mock_api, client: SoltiClient,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr(client_module.time, "sleep", lambda s: sleeps.append(s))
        state = {"count": 0}

        def responder(request):
            state["count"] += 1
            if state["count"] == 1:
                return json_response(status=429)
            return json_response(payload={"jobs": []})

        mock_api.respond_with(responder)
        client.jobs.list()
        assert sleeps == [5.0]

    def test_retries_at_most_twice_then_raises_rate_limit_error(
        self, mock_api, client: SoltiClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)

        def responder(request):
            return json_response(status=429, headers={"Retry-After": "17"})

        mock_api.respond_with(responder)
        with pytest.raises(exceptions.RateLimitError) as excinfo:
            client.jobs.list()
        # 1 initial + 2 retries (client default max_rate_limit_retries=2).
        assert len(mock_api.calls(method="GET", path="/1/jobs")) == 3
        assert excinfo.value.retry_after == 17
        assert excinfo.value.rate_limit_headers == {}  # only X-RateLimit-* captured
        assert excinfo.value.status == 429

    def test_rate_limit_error_exposes_x_ratelimit_headers(self, mock_api, client: SoltiClient,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)

        def responder(request):
            return json_response(
                status=429,
                payload={"code": "rate_limit_exceeded",
                         "message": "Rate limit exceeded for this project. "
                                    "Retry after 17 seconds."},
                headers={"Retry-After": "17", "X-RateLimit-Limit": "120",
                         "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1728123456"},
            )

        mock_api.respond_with(responder)
        with pytest.raises(exceptions.RateLimitError) as excinfo:
            client.jobs.get("j1")  # reads retry too, but exhaust all attempts here
        assert excinfo.value.retry_after == 17
        assert excinfo.value.rate_limit_headers == {
            "X-RateLimit-Limit": "120",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1728123456",
        }
        assert "Rate limit exceeded" in str(excinfo.value)

    def test_mutations_never_auto_retry(self, mock_api, client: SoltiClient,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        mock_api.respond_with(lambda req: json_response(status=429, headers={"Retry-After": "1"}))
        with pytest.raises(exceptions.RateLimitError):
            client.jobs.create(image="alpine:latest")
        assert len(mock_api.calls(method="POST", path="/1/jobs")) == 1

    def test_max_rate_limit_retries_configurable(self, mock_api,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(client_module.time, "sleep", lambda s: None)
        client = SoltiClient(api_key="test-key", api_url=mock_api.base_url,
                             max_rate_limit_retries=0)
        mock_api.respond_with(lambda req: json_response(status=429))
        with pytest.raises(exceptions.RateLimitError):
            client.jobs.list()
        assert len(mock_api.calls(method="GET", path="/1/jobs")) == 1


class TestRetryAfterParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, 5.0),
            ("17", 17.0),
            ("abc", 5.0),   # invalid → CLI default
            ("120", 30.0),  # capped
            ("0", 0.0),
        ],
    )
    def test_parse(self, raw: str | None, expected: float) -> None:
        assert client_module._parse_retry_after(raw) == expected
