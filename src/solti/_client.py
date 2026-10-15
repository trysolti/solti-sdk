"""Solti API transport: auth headers, host strategy, error mapping, 429 retry.

Mirrors `solti-cli/src/api/client.ts`:
- API-key auth via the `X-Solti-API-Key` header.
- Project selection via the `X-Solti-Project-Id` header (per-project wildcard
  hosts are NOT deployed — do not resolve `<project>.api.solti.run`).
- 429 handling: auto-retry idempotent reads (≤2 retries) honoring
  `Retry-After`, capped at 30s; mutations surface `RateLimitError` to the caller.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from .exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SoltiError,
    ValidationError,
)

DEFAULT_API_URL = "https://api.solti.run/1"
PREVIEW_API_URL = "https://preview.api.solti.run/1"

_API_KEY_HEADER = "X-Solti-API-Key"
_PROJECT_HEADER = "X-Solti-Project-Id"

_MAX_RETRY_AFTER_SECONDS = 30.0
_DEFAULT_RETRY_AFTER_SECONDS = 5.0

_STATUS_ERROR_MAP: dict[int, type[SoltiError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
}


def _parse_retry_after(value: str | None) -> float:
    """Parses the `Retry-After` header value in seconds (CLI semantics)."""
    if value is None:
        return _DEFAULT_RETRY_AFTER_SECONDS
    try:
        seconds = float(value)
    except ValueError:
        return _DEFAULT_RETRY_AFTER_SECONDS
    if seconds != seconds:  # NaN — mirrors the CLI's Number.isFinite guard.
        return _DEFAULT_RETRY_AFTER_SECONDS
    return min(seconds, _MAX_RETRY_AFTER_SECONDS)


class _Request:
    """A single API request descriptor (used for retries and error reporting)."""

    def __init__(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.method = method
        self.path = path
        self.json_body = json_body
        self.params = {k: v for k, v in (params or {}).items() if v is not None}


class SoltiClient:
    """Client for the Solti Platform API.

    Args:
        api_key: API key (Zitadel PAT). Falls back to the `SOLTI_API_KEY`
            environment variable when omitted.
        api_url: Base URL of the API (global host or preview). Falls back to
            the `SOLTI_API_URL` environment variable, then
            `https://api.solti.run/1`. Do NOT pass per-project wildcard hosts —
            project selection is done with the `X-Solti-Project-Id` header.
        project_id: Project scoping, sent as `X-Solti-Project-Id`. Falls back
            to the `SOLTI_PROJECT_ID` environment variable.
        timeout: Per-request HTTP timeout in seconds.
        max_rate_limit_retries: Automatic retries for idempotent reads on 429.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        project_id: str | None = None,
        timeout: float = 30.0,
        max_rate_limit_retries: int = 2,
    ) -> None:
        self.api_key = api_key or os.environ.get("SOLTI_API_KEY") or ""
        if not self.api_key:
            raise ValueError(
                "No API key provided. Pass api_key=... or set the "
                "SOLTI_API_KEY environment variable."
            )
        self.api_url = (api_url or os.environ.get("SOLTI_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.project_id = project_id or os.environ.get("SOLTI_PROJECT_ID") or None
        self.timeout = timeout
        self.max_rate_limit_retries = max_rate_limit_retries

        # Resource namespaces (imported here to avoid a circular import).
        from .resources.connections import ConnectionsResource
        from .resources.cronjobs import CronjobsResource
        from .resources.jobs import JobsResource
        from .resources.keys import KeysResource

        self.jobs = JobsResource(self)
        self.connections = ConnectionsResource(self)
        self.cronjobs = CronjobsResource(self)
        self.keys = KeysResource(self)

        self._http = httpx.Client(base_url=self.api_url, timeout=timeout)

    def close(self) -> None:
        """Releases the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> SoltiClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- request plumbing ---------------------------------------------------

    def _headers(self, request: _Request) -> dict[str, str]:
        headers = {_API_KEY_HEADER: self.api_key}
        if self.project_id:
            headers[_PROJECT_HEADER] = self.project_id
        if request.json_body is not None:
            headers["Content-Type"] = "application/json"
        return headers

    def request(
        self,
        path: str,
        method: str = "GET",
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Performs an API request relative to the base URL (e.g. `jobs`).

        Auto-retries idempotent reads (`GET`) on 429, honoring `Retry-After`
        (default 5s, capped at 30s). All other 429s raise `RateLimitError`.
        """
        request = _Request(method, path, json_body=json_body, params=params)
        attempts = 0
        while True:
            attempts += 1
            response = self._http.request(
                request.method,
                request.path,
                headers=self._headers(request),
                json=request.json_body,
                params=request.params,
            )
            if response.status_code == 429:
                if request.method == "GET" and attempts <= self.max_rate_limit_retries:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    time.sleep(retry_after)
                    continue
                raise self._rate_limit_error(response)
            if response.status_code >= 400:
                raise self._error_for(response)
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

    @staticmethod
    def _payload(response: httpx.Response) -> Any:
        text = response.text
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return text

    @classmethod
    def _error_message(cls, response: httpx.Response) -> str:
        payload = cls._payload(response)
        if isinstance(payload, dict):
            for key in ("message", "error", "detail", "code"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value
        if isinstance(payload, str) and payload:
            return payload
        return f"Solti API error (HTTP {response.status_code})"

    @classmethod
    def _error_for(cls, response: httpx.Response) -> SoltiError:
        exc_class = _STATUS_ERROR_MAP.get(response.status_code, SoltiError)
        return exc_class(
            cls._error_message(response),
            status=response.status_code,
            payload=cls._payload(response),
            headers=dict(response.headers),
        )

    @staticmethod
    def _rate_limit_error(response: httpx.Response) -> RateLimitError:
        # Preserve the raw `X-RateLimit-*` header casing (httpx lowercases keys).
        raw = response.headers.raw
        rate_limit_headers = {
            name.decode("latin-1"): value.decode("latin-1")
            for name, value in raw
            if name.decode("latin-1").lower().startswith("x-ratelimit-")
        }
        return RateLimitError(
            SoltiClient._error_message(response),
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            rate_limit_headers=rate_limit_headers,
            status=response.status_code,
            payload=SoltiClient._payload(response),
            headers=dict(response.headers),
        )
