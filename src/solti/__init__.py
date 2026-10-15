"""Solti Platform Python SDK (package `solti-sdk`, import `solti`)."""

from ._client import DEFAULT_API_URL, PREVIEW_API_URL, SoltiClient
from .exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SoltiError,
    TimeoutError,
    ValidationError,
    WorkloadFailedError,
)
from .resources.jobs import Job

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_API_URL",
    "PREVIEW_API_URL",
    "SoltiClient",
    "Job",
    "SoltiError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
    "RateLimitError",
    "WorkloadFailedError",
    "TimeoutError",
    "__version__",
]
