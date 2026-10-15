"""Typed exceptions mapped from Solti API HTTP responses (sdk.md §5)."""

from __future__ import annotations

import builtins
from typing import Any

__all__ = [
    "SoltiError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
    "RateLimitError",
    "WorkloadFailedError",
    "TimeoutError",
]


class SoltiError(Exception):
    """Base class for all Solti SDK errors.

    Attributes:
        status: HTTP status code, if the error originated from an API response.
        payload: Parsed JSON error body (or raw text) from the API, if any.
        headers: Response headers from the failing API response, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload
        self.headers = headers or {}


class AuthenticationError(SoltiError):
    """401 — the API key (Zitadel PAT) is invalid or has expired."""


class PermissionDeniedError(SoltiError):
    """403 — the key's role lacks access (e.g. `viewer` scoped key on a write)."""


class NotFoundError(SoltiError):
    """404 — the requested job / connection / cronjob / key does not exist."""


class ConflictError(SoltiError):
    """409 — a resource with the same unique name already exists."""


class ValidationError(SoltiError):
    """422 — the submitted payload contains invalid configuration."""


class RateLimitError(SoltiError):
    """429 — the API rate limit was exceeded.

    Attributes:
        retry_after: Server-provided `Retry-After` value in seconds (0 if absent).
        rate_limit_headers: The `X-RateLimit-*` response headers as a dict.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: float = 0.0,
        rate_limit_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
        self.rate_limit_headers = rate_limit_headers or {}


class WorkloadFailedError(SoltiError):
    """Raised by `wait_until_complete` when the workload fails.

    Attributes:
        exit_code: Container exit code reported by the Task Manager (if any).
        error_summary: Logged failure summary (if any).
        oom: Whether the workload was killed by the OOM killer.
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        error_summary: str | None = None,
        oom: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.exit_code = exit_code
        self.error_summary = error_summary
        self.oom = oom


class TimeoutError(SoltiError, builtins.TimeoutError):
    """Raised by `wait_until_complete` when the client-side wait timeout elapses.

    Subclasses the built-in `TimeoutError` so both
    `except solti.exceptions.TimeoutError` and `except TimeoutError` catch it.
    """
